"""GitHub Projects v2 (GraphQL) client for the ban log.

The bot talks to GitHub directly: Muse's GitHub connector has no Projects
tools, and Projects v2 is GraphQL-only. The token comes from the
GITHUB_PROJECT_TOKEN env var (set it in .env next to TOKEN2, never in
chat). Target project defaults to the test board (poos241 project 2);
override with GITHUB_PROJECT_OWNER / GITHUB_PROJECT_NUMBER when the real
board is wired up.
"""

import os

import aiohttp

API_URL = "https://api.github.com/graphql"

PROJECT_OWNER = os.getenv("GITHUB_PROJECT_OWNER", "poos241")
PROJECT_NUMBER = int(os.getenv("GITHUB_PROJECT_NUMBER", "2"))


async def _graphql(token, query, variables=None):
    headers = {
        "Authorization": "Bearer " + token,
        "Content-Type": "application/json",
    }
    payload = {"query": query, "variables": variables or {}}
    async with aiohttp.ClientSession() as session:
        async with session.post(API_URL, json=payload, headers=headers) as resp:
            data = await resp.json()
    if "errors" in data:
        messages = "; ".join(e.get("message", "?") for e in data["errors"])
        raise RuntimeError("GitHub API error: " + messages)
    return data.get("data") or {}


async def get_project_id(token):
    """Resolve the configured project to its node ID (no hardcoded IDs)."""
    query = """
        query($login: String!, $number: Int!) {
            user(login: $login) {
                projectV2(number: $number) { id title }
            }
        }
    """
    data = await _graphql(token, query, {"login": PROJECT_OWNER, "number": PROJECT_NUMBER})
    project = (data.get("user") or {}).get("projectV2")
    if not project:
        raise RuntimeError(
            "Project not found: user %s project %s (check owner/number/token access)"
            % (PROJECT_OWNER, PROJECT_NUMBER)
        )
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
            user(login: $login) {
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
    data = await _graphql(token, query, {"login": PROJECT_OWNER, "number": PROJECT_NUMBER})
    project = (data.get("user") or {}).get("projectV2")
    if not project:
        raise RuntimeError(
            "Project not found: user %s project %s (check owner/number/token access)"
            % (PROJECT_OWNER, PROJECT_NUMBER)
        )
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
            user(login: $login) {
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
    data = await _graphql(token, query, {"login": PROJECT_OWNER, "number": PROJECT_NUMBER})
    project = (data.get("user") or {}).get("projectV2")
    if not project:
        raise RuntimeError(
            "Project not found: user %s project %s (check owner/number/token access)"
            % (PROJECT_OWNER, PROJECT_NUMBER)
        )
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


async def _snapshot_item_values(token):
    """All board items' single-select field values.

    Returns {item_id: {field_name: option_name}}. Used before an
    option-list update: replacing a field's options can clear the
    values on items that used the old options, so the setup helper
    re-asserts any value that got cleared.
    """
    query = """
        query($login: String!, $number: Int!) {
            user(login: $login) {
                projectV2(number: $number) {
                    items(first: 100) {
                        nodes {
                            id
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
    data = await _graphql(token, query, {"login": PROJECT_OWNER, "number": PROJECT_NUMBER})
    snapshot = {}
    for item in (data.get("user") or {}).get("projectV2", {}).get("items", {}).get("nodes", []):
        values = {}
        for fv in (item.get("fieldValues") or {}).get("nodes", []):
            fname = (fv.get("field") or {}).get("name")
            if fname and fv.get("name"):
                values[fname] = fv["name"]
        snapshot[item["id"]] = values
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
            user(login: $login) {
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
    data = await _graphql(token, query, {"login": PROJECT_OWNER, "number": PROJECT_NUMBER})
    items = []
    for node in (data.get("user") or {}).get("projectV2", {}).get("items", {}).get("nodes", []):
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
    set before) gets its old value written back. Returns the number
    of values restored.
    """
    after = await _snapshot_item_values(token)
    restored = 0
    for item_id, values in before.items():
        now = after.get(item_id, {})
        for field_name, option_name in values.items():
            if now.get(field_name):
                continue
            field = fields.get(field_name)
            if not field:
                continue
            option_id = field["options"].get(option_name)
            if not option_id:
                continue
            await set_single_select(
                token, project_id, item_id, field["id"], option_id
            )
            restored += 1
    return restored


async def ensure_approval_setup(token):
    """One-time board setup for the approval flow (go-live helper).

    Creates the Approval field when missing, adds the "Needs approval"
    option to Status when missing, adds the "pending approval" /
    "approved" options to tags when missing, and creates the Decision
    field (Blacklist approved / more info) when missing, preserving
    the existing options exactly (name, color, description). Replacing
    a field's option list can clear the values on items that used the
    old options, so any value that gets cleared is written back.
    Returns (approval_field_id, status_has_needs_approval). Run it
    against a board before the bot starts posting approval-flow cases
    there.
    """
    project_id, fields = await get_project_fields_detailed(token)
    approval_id = await create_approval_field(token, project_id)
    # Snapshot the items' values first: an option-list update can
    # clear them, and they get written back below.
    before = await _snapshot_item_values(token)
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
    # item value the option updates cleared.
    _, fields = await get_project_fields_detailed(token)
    await _restore_cleared_values(token, project_id, fields, before)
    return approval_id, status_ok


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
