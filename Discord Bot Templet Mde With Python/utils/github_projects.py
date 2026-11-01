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


async def create_logged_case(token, title, body, status=None, tags=None):
    """Create a case item and set Status/tags when asked.

    Returns (item_id, warnings). A field/option that no longer exists on
    the board produces a warning, not a failure: the item itself is
    already posted, and staff can fix the field on the board.
    """
    project_id, fields = await get_project_fields(token)
    item_id = await create_draft_issue(token, project_id, title, body)
    warnings = []
    for field_name, option_name in (("Status", status), ("tags", tags)):
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
