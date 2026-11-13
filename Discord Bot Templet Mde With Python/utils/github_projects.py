"""GitHub Projects v2 (GraphQL) client for the ban log.

The bot talks to GitHub directly: Muse's GitHub connector has no Projects
tools, and Projects v2 is GraphQL-only. The token comes from the
GITHUB_PROJECT_TOKEN env var (set it in .env next to TOKEN2, never in
chat). Target project defaults to the test board (poos241 project 2);
override with GITHUB_PROJECT_OWNER / GITHUB_PROJECT_NUMBER when the real
board is wired up. The owner is read from the environment on every
call (not once at import), and may be a personal account or an
organization: every project query tries user(login:) first, then
organization(login:), so a board that moves to an org keeps working.
(Editing .env still needs a bot restart — the process environment is
loaded from .env at startup.)
"""

import asyncio
import logging
import os

import aiohttp

logger = logging.getLogger(__name__)

API_URL = "https://api.github.com/graphql"

DEFAULT_PROJECT_OWNER = "poos241"
DEFAULT_PROJECT_NUMBER = 2


def get_project_owner():
    """Configured board owner, read from the environment on every call.

    Deliberately not a module-level constant: a board switch (test
    board -> real board) takes effect on the next call instead of
    needing the value frozen at import time.
    """
    return os.getenv("GITHUB_PROJECT_OWNER", DEFAULT_PROJECT_OWNER)


def get_project_number():
    """Configured board number, read from the environment on every call."""
    raw = os.getenv("GITHUB_PROJECT_NUMBER", str(DEFAULT_PROJECT_NUMBER))
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise RuntimeError(
            "GITHUB_PROJECT_NUMBER is not a number: %r" % (raw,)
        )

# Snapshot safety cap: ensure_approval_setup refuses to rewrite a
# field's option list on a board with more items than this, because a
# value cleared on an item that was never snapshotted could never be
# restored. The snapshot pages over the whole board (see
# _snapshot_item_values), so the cap is a guard against an unbounded
# board, not a page size.
SNAPSHOT_MAX_ITEMS = 1000
# GitHub's max page size for a connection.
SNAPSHOT_PAGE_SIZE = 100

# --- GraphQL transport -------------------------------------------------
# The old _graphql built a fresh aiohttp.ClientSession per call with no
# timeout, never checked resp.status, and never handled 429s: a hung or
# rate-limited GitHub stalled the calling interaction for up to
# aiohttp's 5-minute default, a 429/502 HTML error page raised a
# confusing ContentTypeError, and a burst of ban-log commands churned
# a new TCP/TLS session per GraphQL call (create + 3 field sets +
# resolve is 5+ sessions per post). All calls now share one session
# with a 30-second total timeout, and 429s back off (see _graphql).

# Total budget for one GraphQL round trip (connect + read). A hung
# GitHub fails the interaction after this instead of stalling it.
GRAPHQL_TIMEOUT_SECONDS = 30
_GRAPHQL_TIMEOUT = aiohttp.ClientTimeout(total=GRAPHQL_TIMEOUT_SECONDS)
# Retries for a rate-limited request (HTTP 429 or a RATE_LIMITED
# GraphQL error). Each attempt still has the 30s timeout above.
_GRAPHQL_MAX_ATTEMPTS = 3
# Longest we ever wait on a Retry-After / backoff delay: a huge
# Retry-After header must not park the interaction for minutes.
_GRAPHQL_MAX_BACKOFF_SECONDS = 60

_SESSION = None
_SESSION_LOOP = None


async def _get_session():
    """The one shared session for all GraphQL calls.

    One TCP/TLS setup, reused across the create + field-set calls of
    a single post instead of a fresh session per call. The session is
    bound to the event loop that created it, so a different running
    loop gets a fresh session (the old one is dropped, not closed —
    its loop is gone). Callers never construct a session themselves.
    """
    global _SESSION, _SESSION_LOOP
    loop = asyncio.get_running_loop()
    if _SESSION is None or _SESSION.closed or _SESSION_LOOP is not loop:
        _SESSION = aiohttp.ClientSession(timeout=_GRAPHQL_TIMEOUT)
        _SESSION_LOOP = loop
    return _SESSION


async def close_github_session():
    """Close the shared session (bot shutdown / tests).

    Safe to call when no session exists, or from a different loop
    than the session's (the session is then dropped, not closed —
    closing it from the wrong loop would raise). The session is
    otherwise left open for the life of the process on purpose: the
    bot has no graceful-shutdown hook (shutdown calls os._exit).
    """
    global _SESSION, _SESSION_LOOP
    if _SESSION is not None:
        if not _SESSION.closed and _SESSION_LOOP is asyncio.get_running_loop():
            await _SESSION.close()
        _SESSION = None
        _SESSION_LOOP = None


def _retry_after_seconds(resp, attempt):
    """How long to wait before retrying a rate-limited request.

    Honors GitHub's Retry-After header (seconds) when present and
    parseable, capped at _GRAPHQL_MAX_BACKOFF_SECONDS; otherwise an
    exponential backoff (2s, 4s, ...) from the attempt number. resp
    may be None (GraphQL RATE_LIMITED errors carry no HTTP headers
    of their own — the delay then always comes from the backoff).
    """
    if resp is not None:
        raw = resp.headers.get("Retry-After")
        if raw is not None:
            try:
                return max(0, min(int(raw), _GRAPHQL_MAX_BACKOFF_SECONDS))
            except (TypeError, ValueError):
                pass
    return min(2 ** attempt, _GRAPHQL_MAX_BACKOFF_SECONDS)


def _is_rate_limited(errors):
    """True when a GraphQL errors list is a rate-limit rejection.

    GitHub's GraphQL API can answer a rate limit with HTTP 200 and
    an errors entry of type RATE_LIMITED instead of an HTTP 429, so
    both shapes are retried the same way.
    """
    return any(
        isinstance(e, dict) and e.get("type") == "RATE_LIMITED"
        for e in errors or []
    )


async def _safe_body_text(resp):
    """A short snippet of a non-200 response body for the error line.

    Error pages can be long HTML; the first 200 characters are
    enough to tell a proxy 502 from a GitHub message, and the rest
    is never needed in a staff-facing reply.
    """
    try:
        text = await resp.text()
    except Exception:
        return "(unreadable body)"
    text = " ".join((text or "").split())
    return text[:200] or "(empty body)"


async def _graphql(token, query, variables=None):
    """One GraphQL round trip against api.github.com.

    All calls share one session (see _get_session) with a 30-second
    total timeout, so a hung GitHub fails the interaction after 30s
    instead of stalling it for aiohttp's 5-minute default. HTTP
    status is checked before the body is parsed: a 429/502 HTML
    error page used to raise a confusing ContentTypeError from
    resp.json(); it now raises a RuntimeError naming the status.
    A 429 (or a GraphQL RATE_LIMITED error) is retried after the
    Retry-After delay, up to _GRAPHQL_MAX_ATTEMPTS attempts — GitHub
    rejects a rate-limited request before executing it, so retrying
    cannot double-post a case. Timeouts, connection errors and 5xx
    responses are NOT retried: a timed-out mutation may already have
    executed server-side, and retrying it could create a duplicate
    board item, so those fail loud instead.
    """
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}
    session = await _get_session()
    for attempt in range(1, _GRAPHQL_MAX_ATTEMPTS + 1):
        try:
            async with session.post(API_URL, json=payload, headers=headers) as resp:
                if resp.status == 429:
                    if attempt < _GRAPHQL_MAX_ATTEMPTS:
                        delay = _retry_after_seconds(resp, attempt)
                        logger.warning(
                            "GitHub rate limited (HTTP 429); retrying in %ss "
                            "(attempt %d/%d)",
                            delay, attempt, _GRAPHQL_MAX_ATTEMPTS,
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise RuntimeError(
                        "GitHub rate limit (HTTP 429) after %d attempts; "
                        "try again later" % _GRAPHQL_MAX_ATTEMPTS
                    )
                if resp.status != 200:
                    body = await _safe_body_text(resp)
                    raise RuntimeError(
                        "GitHub API HTTP %d: %s" % (resp.status, body)
                    )
                try:
                    data = await resp.json()
                except (aiohttp.ContentTypeError, ValueError) as exc:
                    raise RuntimeError(
                        "GitHub returned a non-JSON response (HTTP %d): %s"
                        % (resp.status, exc)
                    )
        except asyncio.TimeoutError:
            raise RuntimeError(
                "GitHub request timed out after %ds; the board was not "
                "reached — try again" % GRAPHQL_TIMEOUT_SECONDS
            )
        except aiohttp.ClientError as exc:
            raise RuntimeError("GitHub request failed: %s" % exc)
        if "errors" in data:
            if _is_rate_limited(data["errors"]):
                if attempt < _GRAPHQL_MAX_ATTEMPTS:
                    delay = _retry_after_seconds(None, attempt)
                    logger.warning(
                        "GitHub rate limited (RATE_LIMITED); retrying in "
                        "%ss (attempt %d/%d)",
                        delay, attempt, _GRAPHQL_MAX_ATTEMPTS,
                    )
                    await asyncio.sleep(delay)
                    continue
                raise RuntimeError(
                    "GitHub rate limit (RATE_LIMITED) after %d attempts; "
                    "try again later" % _GRAPHQL_MAX_ATTEMPTS
                )
            messages = "; ".join(e.get("message", "?") for e in data["errors"])
            raise RuntimeError("GitHub API error: " + messages)
        return data.get("data") or {}
    # Unreachable: every path above either returns, raises, or
    # continues, and the loop only exits via return/raise.
    raise RuntimeError("GitHub request failed: no response")  # pragma: no cover


async def _query_project(token, query_template, variables=None):
    """Run a projectV2 query against the configured board.

    query_template is a GraphQL query with a __ROOT__ placeholder
    where `user` or `organization` goes. The owner is tried as a
    GitHub user first, then as an organization: a personal board
    lives under user(login:), an org board under
    organization(login:), and querying the wrong root just returns
    null instead of an error. Returns (project, is_org).

    Raises RuntimeError when neither root has the project, naming
    the owner and number so a misconfigured board reads as a config
    problem instead of a bare "Project not found". Verified 2026-11-06
    that the real board owner Spiderella007 is a personal account, so
    the user root resolves it today; the organization fallback is
    what keeps this working if the board ever moves to an org.
    """
    owner = get_project_owner()
    number = get_project_number()
    query_vars = {"login": owner, "number": number}
    if variables:
        query_vars.update(variables)
    for root, is_org in (("user", False), ("organization", True)):
        query = query_template.replace("__ROOT__", root)
        data = await _graphql(token, query, query_vars)
        project = (data.get(root) or {}).get("projectV2")
        if project:
            return project, is_org
    raise RuntimeError(
        "Project not found: owner %s project %s (check owner/number/token "
        "access; the owner must be a GitHub user or an organization)"
        % (owner, number)
    )


async def get_board_url(token):
    """Public web URL of the configured board.

    Personal boards live at github.com/users/<login>/projects/<n>;
    org boards at github.com/orgs/<login>/projects/<n>. The owner
    type is resolved live (same user-then-organization probe as the
    project queries), so the link staff get never 404s when the
    board moves to an org.
    """
    _project, is_org = await _query_project(
        token,
        "query($login: String!, $number: Int!) { "
        "__ROOT__(login: $login) { projectV2(number: $number) { id } } }",
    )
    kind = "orgs" if is_org else "users"
    return "https://github.com/%s/%s/projects/%s" % (
        kind, get_project_owner(), get_project_number()
    )


async def get_project_id(token):
    """Resolve the configured project to its node ID (no hardcoded IDs)."""
    query = """
        query($login: String!, $number: Int!) {
            __ROOT__(login: $login) {
                projectV2(number: $number) { id title }
            }
        }
    """
    project, _is_org = await _query_project(token, query)
    return project["id"]


async def create_draft_issue(token, project_id, title, body):
    """Create a draft item on the project. Returns the item node ID."""
    mutation = """
        mutation($projectId: ID!, $title: String!, $body: String!) {
            addProjectV2DraftIssue(input: {
                projectId: $projectId, title: $title, body: $body
            }) {
                projectItem { id }
            }
        }
    """
    data = await _graphql(
        token,
        mutation,
        {"projectId": project_id, "title": title, "body": body},
    )
    item = (data.get("addProjectV2DraftIssue") or {}).get("projectItem") or {}
    if not item.get("id"):
        raise RuntimeError("GitHub accepted the request but returned no item ID")
    return item["id"]


async def get_project_fields(token):
    """Resolve the project and its fields.

    Returns (project_id, fields) where fields maps field name -> {
    "id": field node id, "options": {option name: option id} }.
    Names are used (not hardcoded IDs) so board edits surface as clear
    errors instead of silent mismatches.
    """
    query = """
        query($login: String!, $number: Int!) {
            __ROOT__(login: $login) {
                projectV2(number: $number) {
                    id
                    fields(first: 100) {
                        nodes {
                            __typename
                            ... on ProjectV2Field { id name }
                            ... on ProjectV2SingleSelectField {
                                id name
                                options { id name }
                            }
                        }
                    }
                }
            }
        }
    """
    project, _is_org = await _query_project(token, query)
    fields = {}
    for node in (project.get("fields") or {}).get("nodes") or []:
        name = node.get("name")
        if not name:
            continue
        entry = {"id": node.get("id"), "options": {}}
        for opt in node.get("options") or []:
            if opt.get("name"):
                entry["options"][opt["name"]] = opt.get("id")
        fields[name] = entry
    return project["id"], fields


async def set_single_select(token, project_id, item_id, field_id, option_id):
    """Set one single-select field on an existing project item."""
    mutation = """
        mutation($projectId: ID!, $itemId: ID!, $fieldId: ID!, $optionId: String!) {
            updateProjectV2ItemFieldValue(input: {
                projectId: $projectId, itemId: $itemId, fieldId: $fieldId,
                value: { singleSelectOptionId: $optionId }
            }) {
                projectV2Item { id }
            }
        }
    """
    await _graphql(
        token,
        mutation,
        {
            "projectId": project_id,
            "itemId": item_id,
            "fieldId": field_id,
            "optionId": option_id,
        },
    )


async def set_field_by_name(token, project_id, item_id, field_name, option_name):
    """Set one single-select field by name (resolves field + option IDs).

    Used by /log_approve. Raises a clear error when the field or the
    option does not exist on the board, so a missing Approval field
    surfaces as a readable message instead of a silent no-op.
    """
    project_id, fields = await get_project_fields(token)
    field = fields.get(field_name)
    if not field:
        raise RuntimeError("Board has no %s field." % field_name)
    option_id = field["options"].get(option_name)
    if not option_id:
        raise RuntimeError(
            "Board %s has no option %r." % (field_name, option_name)
        )
    await set_single_select(token, project_id, item_id, field["id"], option_id)


async def get_project_fields_detailed(token):
    """Like get_project_fields, but each option also carries color and
    description. Needed when rewriting a field's option list (adding an
    option replaces the whole list, so the existing options must be
    passed back exactly as they are)."""
    query = """
        query($login: String!, $number: Int!) {
            __ROOT__(login: $login) {
                projectV2(number: $number) {
                    id
                    fields(first: 100) {
                        nodes {
                            __typename
                            ... on ProjectV2Field { id name }
                            ... on ProjectV2SingleSelectField {
                                id name
                                options { id name color description }
                            }
                        }
                    }
                }
            }
        }
    """
    project, _is_org = await _query_project(token, query)
    fields = {}
    for node in (project.get("fields") or {}).get("nodes") or []:
        name = node.get("name")
        if not name:
            continue
        entry = {"id": node.get("id"), "options": {}}
        for opt in node.get("options") or []:
            if opt.get("name"):
                entry["options"][opt["name"]] = {
                    "id": opt.get("id"),
                    "color": opt.get("color"),
                    "description": opt.get("description") or "",
                }
        fields[name] = entry
    return project["id"], fields


async def create_approval_field(token, project_id):
    """Create the Approval single-select field (Needs approval / Log
    approved). No-op when it already exists. Returns the field id."""
    project_id, fields = await get_project_fields(token)
    if "Approval" in fields:
        return fields["Approval"]["id"]
    mutation = """
        mutation($projectId: ID!, $name: String!, $dataType: ProjectV2CustomFieldType!, $singleSelectOptions: [ProjectV2SingleSelectFieldOptionInput!]) {
            createProjectV2Field(input: {projectId: $projectId, dataType: $dataType, name: $name, singleSelectOptions: $singleSelectOptions}) {
                projectV2Field {
                    ... on ProjectV2SingleSelectField { id name }
                }
            }
        }
    """
    data = await _graphql(
        token,
        mutation,
        {
            "projectId": project_id,
            "name": "Approval",
            "dataType": "SINGLE_SELECT",
            "singleSelectOptions": [
                {"name": "Needs approval", "color": "YELLOW",
                 "description": "Waiting for a second staff member to review and approve."},
                {"name": "Log approved", "color": "GREEN",
                 "description": "Reviewed and approved by a second staff member."},
            ],
        },
    )
    field = (data.get("createProjectV2Field") or {}).get("projectV2Field") or {}
    if not field.get("id"):
        raise RuntimeError("GitHub accepted the request but returned no field ID")
    return field["id"]


_SNAPSHOT_ITEMS_QUERY = """
    query($login: String!, $number: Int!, $after: String) {
        __ROOT__(login: $login) {
            projectV2(number: $number) {
                items(first: 100, after: $after) {
                    nodes {
                        id
                        fieldValues(first: 100) {
                            nodes {
                                ... on ProjectV2ItemFieldSingleSelectValue {
                                    name
                                    field { ... on ProjectV2SingleSelectField { name } }
                                }
                            }
                            pageInfo { hasNextPage endCursor }
                        }
                    }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }
    }
"""

_ITEM_FIELD_VALUES_QUERY = """
    query($itemId: ID!, $after: String) {
        node(id: $itemId) {
            ... on ProjectV2Item {
                fieldValues(first: 100, after: $after) {
                    nodes {
                        ... on ProjectV2ItemFieldSingleSelectValue {
                            name
                            field { ... on ProjectV2SingleSelectField { name } }
                        }
                    }
                    pageInfo { hasNextPage endCursor }
                }
            }
        }
    }
"""


def _collect_field_values(values, nodes):
    """Fold one page of fieldValues nodes into {field_name: option_name}."""
    for fv in nodes or []:
        fname = (fv.get("field") or {}).get("name")
        if fname and fv.get("name"):
            values[fname] = fv["name"]


async def _snapshot_item_values(token):
    """All board items' single-select field values.

    Returns {item_id: {field_name: option_name}}. Used before an
    option-list update: replacing a field's options can clear the
    values on items that used the old options, so the setup helper
    re-asserts any value that got cleared.

    The snapshot pages over EVERY item on the board (and over every
    field value on each item) instead of taking only the first page:
    a value past the first 100 items (or the first 20 field values)
    is just as clearable, and without a full snapshot it would be
    lost with no record it ever existed.

    Raises RuntimeError when the board holds more than
    SNAPSHOT_MAX_ITEMS items: refusing to rewrite an option list
    whose cleared values could not all be snapshotted first. Call
    this before any option-list mutation, so the refusal happens
    while the board is still untouched.
    """
    snapshot = {}
    after = None
    total = 0
    while True:
        project, _is_org = await _query_project(
            token, _SNAPSHOT_ITEMS_QUERY, {"after": after}
        )
        items = project.get("items", {}) or {}
        for node in items.get("nodes") or []:
            total += 1
            if total > SNAPSHOT_MAX_ITEMS:
                raise RuntimeError(
                    "Board has more than %d items; refusing to rewrite "
                    "options without a full snapshot (snapshot cap %d)"
                    % (SNAPSHOT_MAX_ITEMS, SNAPSHOT_MAX_ITEMS)
                )
            item_id = node.get("id")
            if not item_id:
                continue
            values = {}
            fvs = node.get("fieldValues") or {}
            _collect_field_values(values, fvs.get("nodes"))
            fv_page = fvs.get("pageInfo") or {}
            while fv_page.get("hasNextPage"):
                cursor = fv_page.get("endCursor")
                if cursor is None:
                    raise RuntimeError(
                        "Board pagination stalled: fieldValues reports "
                        "another page for item %s but gives no cursor"
                        % item_id
                    )
                more = await _graphql(
                    token, _ITEM_FIELD_VALUES_QUERY,
                    {"itemId": item_id, "after": cursor},
                )
                fvs = ((more.get("node") or {}).get("fieldValues") or {})
                _collect_field_values(values, fvs.get("nodes"))
                fv_page = fvs.get("pageInfo") or {}
            snapshot[item_id] = values
        page = items.get("pageInfo") or {}
        if not page.get("hasNextPage"):
            break
        after = page.get("endCursor")
        if after is None:
            raise RuntimeError(
                "Board pagination stalled: items reports another page "
                "but gives no cursor"
            )
    return snapshot


async def list_project_items(token):
    """Every board item with its draft title/body and field values.

    Returns a list of dicts: {item_id, draft_id, title, body,
    is_draft, fields: {field_name: option_name}}. Only draft issues
    carry a title/body the bot can rewrite (hand-made logs are draft
    issues too); a linked real issue has is_draft False and no
    draft_id, so the backfill skips it. Used by /ghlog_backfill_cases
    to find board items without a case number in their title.
    """
    query = """
        query($login: String!, $number: Int!) {
            __ROOT__(login: $login) {
                projectV2(number: $number) {
                    items(first: 100) {
                        nodes {
                            id
                            content {
                                __typename
                                ... on DraftIssue {
                                    id
                                    title
                                    body
                                }
                            }
                            fieldValues(first: 20) {
                                nodes {
                                    ... on ProjectV2ItemFieldSingleSelectValue {
                                        name
                                        field { ... on ProjectV2SingleSelectField { name } }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    """
    project, _is_org = await _query_project(token, query)
    items = []
    for node in project.get("items", {}).get("nodes", []):
        content = node.get("content") or {}
        is_draft = content.get("__typename") == "DraftIssue"
        fields = {}
        for fv in (node.get("fieldValues") or {}).get("nodes", []):
            fname = (fv.get("field") or {}).get("name")
            if fname and fv.get("name"):
                fields[fname] = fv["name"]
        items.append({
            "item_id": node.get("id") or "",
            "draft_id": content.get("id") if is_draft else None,
            "title": content.get("title") or "" if is_draft else "",
            "body": content.get("body") or "" if is_draft else "",
            "is_draft": is_draft,
            "fields": fields,
        })
    return items


async def _restore_cleared_values(token, project_id, fields, before):
    """Re-set any single-select value an option update cleared.

    before is the snapshot from _snapshot_item_values. After the
    options change, an item whose field value is now empty (but was
    set before) gets its old value written back. Each restore is
    attempted even when an earlier one failed, so one bad item cannot
    leave the rest unrestored — and every value that cannot be
    written back is reported instead of silently dropped.

    Returns (restored, failed): restored is the number of values
    written back; failed is a list of {item_id, field, option,
    error} for every value that could not be restored (field or
    option gone from the board, or the write itself failed).
    """
    after = await _snapshot_item_values(token)
    restored = 0
    failed = []
    for item_id, values in before.items():
        now = after.get(item_id, {})
        for field_name, option_name in values.items():
            if now.get(field_name):
                continue
            field = fields.get(field_name)
            if not field:
                failed.append({
                    "item_id": item_id, "field": field_name,
                    "option": option_name,
                    "error": "board no longer has a %s field" % field_name,
                })
                continue
            option = field["options"].get(option_name)
            if not option:
                failed.append({
                    "item_id": item_id, "field": field_name,
                    "option": option_name,
                    "error": "board %s no longer has option %r"
                    % (field_name, option_name),
                })
                continue
            # get_project_fields_detailed maps option names to dicts
            # (id/color/description); get_project_fields maps them to
            # plain ids. The mutation needs the id string either way.
            option_id = (
                option.get("id") if isinstance(option, dict) else option
            )
            if not option_id:
                failed.append({
                    "item_id": item_id, "field": field_name,
                    "option": option_name,
                    "error": "board %s option %r has no id"
                    % (field_name, option_name),
                })
                continue
            try:
                await set_single_select(
                    token, project_id, item_id, field["id"], option_id
                )
            except Exception as exc:
                failed.append({
                    "item_id": item_id, "field": field_name,
                    "option": option_name, "error": str(exc),
                })
                continue
            restored += 1
    return restored, failed


async def ensure_approval_setup(token):
    """One-time board setup for the approval flow (go-live helper).

    Creates the Approval field when missing, adds the "Needs approval"
    option to Status when missing, adds the "pending approval" /
    "approved" options to tags when missing, and creates the Decision
    field (Blacklist approved / more info) when missing, preserving
    the existing options exactly (name, color, description). Replacing
    a field's option list can clear the values on items that used the
    old options, so any value that gets cleared is written back.
    Returns (approval_field_id, status_has_needs_approval, restored,
    failed): restored is the number of cleared values written back
    (0 when no option update cleared anything), and failed lists any
    cleared value that could not be restored. Run it against a board
    before the bot starts posting approval-flow cases there.

    Refuses to run on a board with more than SNAPSHOT_MAX_ITEMS
    items: the snapshot is taken before any option list is rewritten,
    so the refusal happens while the board is still untouched.
    Raises RuntimeError when some cleared values could not be
    restored — the board is then half-updated and the message names
    exactly which values are still missing.
    """
    # Snapshot the items' values FIRST: an option-list update can
    # clear them, and they get written back below. A board over the
    # snapshot cap raises here, before any field or option is touched.
    before = await _snapshot_item_values(token)
    project_id, fields = await get_project_fields_detailed(token)
    approval_id = await create_approval_field(token, project_id)
    status = fields.get("Status")
    if not status:
        raise RuntimeError("Board has no Status field.")
    existing = [
        {"name": name, "color": info.get("color"),
         "description": info.get("description") or ""}
        for name, info in status["options"].items()
    ]
    if "Needs approval" in status["options"]:
        status_ok = True
    else:
        mutation = """
            mutation($fieldId: ID!, $name: String!, $singleSelectOptions: [ProjectV2SingleSelectFieldOptionInput!]) {
                updateProjectV2Field(input: {fieldId: $fieldId, name: $name, singleSelectOptions: $singleSelectOptions}) {
                    projectV2Field {
                        ... on ProjectV2SingleSelectField { id name }
                    }
                }
            }
        """
        await _graphql(
            token,
            mutation,
            {
                "fieldId": status["id"],
                "name": "Status",
                "singleSelectOptions": existing
                + [{"name": "Needs approval", "color": "YELLOW",
                    "description": "Waiting for a second staff member to review and approve."}],
            },
        )
        status_ok = True
    # The bot owns the tags field for the approval state, so the board
    # needs the "pending approval" and "approved" tag options too.
    tags = fields.get("tags")
    if not tags:
        raise RuntimeError("Board has no tags field.")
    existing_tags = [
        {"name": name, "color": info.get("color"),
         "description": info.get("description") or ""}
        for name, info in tags["options"].items()
    ]
    add_tags = []
    if "pending approval" not in tags["options"]:
        add_tags.append({"name": "pending approval", "color": "YELLOW",
                         "description": "Waiting for a second staff member to review and approve."})
    if "approved" not in tags["options"]:
        add_tags.append({"name": "approved", "color": "GREEN",
                         "description": "Reviewed and approved by a second staff member."})
    if add_tags:
        mutation = """
            mutation($fieldId: ID!, $name: String!, $singleSelectOptions: [ProjectV2SingleSelectFieldOptionInput!]) {
                updateProjectV2Field(input: {fieldId: $fieldId, name: $name, singleSelectOptions: $singleSelectOptions}) {
                    projectV2Field {
                        ... on ProjectV2SingleSelectField { id name }
                    }
                }
            }
        """
        await _graphql(
            token,
            mutation,
            {
                "fieldId": tags["id"],
                "name": "tags",
                "singleSelectOptions": existing_tags + add_tags,
            },
        )
    # The Decision field holds a human decision marker (for example
    # "Blacklist approved"). A single-select holds only one value, so
    # it cannot share the tags field with the approval state.
    decision = fields.get("Decision")
    if not decision:
        mutation = """
            mutation($projectId: ID!, $dataType: ProjectV2CustomFieldType!, $name: String!, $singleSelectOptions: [ProjectV2SingleSelectFieldOptionInput!]) {
                createProjectV2Field(input: {projectId: $projectId, dataType: $dataType, name: $name, singleSelectOptions: $singleSelectOptions}) {
                    projectV2Field {
                        ... on ProjectV2SingleSelectField { id name }
                    }
                }
            }
        """
        await _graphql(
            token,
            mutation,
            {
                "projectId": project_id,
                "dataType": "SINGLE_SELECT",
                "name": "Decision",
                "singleSelectOptions": [
                    {"name": "Blacklist approved", "color": "RED",
                     "description": "Approved for the blacklist."},
                    {"name": "more info", "color": "GRAY",
                     "description": "Needs more information before a decision."},
                ],
            },
        )
    # Re-fetch the fields (a new Decision field changes the map, and
    # an option update can change option ids), then write back any
    # item value the option updates cleared. A failed restore is
    # loud: the caller gets the count and the exact values still
    # missing instead of a silent success on a half-updated board.
    _, fields = await get_project_fields_detailed(token)
    restored, failed = await _restore_cleared_values(
        token, project_id, fields, before
    )
    if failed:
        detail = "; ".join(
            "item %s %s=%r (%s)" % (
                f["item_id"], f["field"], f["option"], f["error"]
            )
            for f in failed
        )
        raise RuntimeError(
            "Restored %d cleared value(s) but %d could not be "
            "restored: %s" % (restored, len(failed), detail)
        )
    return approval_id, status_ok, restored, failed


async def create_logged_case(token, title, body, status=None, tags=None, approval=None):
    """Create a case item and set Status/tags/Approval when asked.

    Returns (item_id, warnings). A field/option that no longer exists on
    the board produces a warning, not a failure: the item itself is
    already posted, and staff can fix the field on the board.
    """
    project_id, fields = await get_project_fields(token)
    item_id = await create_draft_issue(token, project_id, title, body)
    warnings = []
    for field_name, option_name in (
        ("Status", status),
        ("tags", tags),
        ("Approval", approval),
    ):
        if not option_name:
            continue
        field = fields.get(field_name)
        if not field:
            warnings.append("Board has no %s field; left unset." % field_name)
            continue
        option_id = field["options"].get(option_name)
        if not option_id:
            warnings.append(
                "Board %s has no option %r; left unset." % (field_name, option_name)
            )
            continue
        await set_single_select(token, project_id, item_id, field["id"], option_id)
    return item_id, warnings


async def resolve_draft_issue_id(token, item_id):
    """Draft issues have their own node ID, distinct from the item ID.

    The update mutation needs the draft issue ID, so resolve it from the
    item first. (Verified live 2026-10-29: node content type DraftIssue.)
    """
    query = """
        query($itemId: ID!) {
            node(id: $itemId) {
                ... on ProjectV2Item {
                    content {
                        ... on DraftIssue { id }
                    }
                }
            }
        }
    """
    data = await _graphql(token, query, {"itemId": item_id})
    content = ((data.get("node") or {}).get("content") or {})
    draft_id = content.get("id")
    if not draft_id:
        raise RuntimeError("Could not resolve a draft issue for that item")
    return draft_id


async def update_draft_issue(token, draft_id, title, body):
    """Rewrite a draft item's title/body (used to append update notes)."""
    mutation = """
        mutation($draftId: ID!, $title: String!, $body: String!) {
            updateProjectV2DraftIssue(input: {
                draftIssueId: $draftId, title: $title, body: $body
            }) {
                draftIssue { id }
            }
        }
    """
    await _graphql(token, mutation, {"draftId": draft_id, "title": title, "body": body})


async def delete_project_item(token, project_id, item_id):
    """Delete an item from the project (used by /banlog_delete)."""
    mutation = """
        mutation($projectId: ID!, $itemId: ID!) {
            deleteProjectV2Item(input: {
                projectId: $projectId, itemId: $itemId
            }) {
                deletedItemId
            }
        }
    """
    await _graphql(
        token, mutation, {"projectId": project_id, "itemId": item_id}
    )
