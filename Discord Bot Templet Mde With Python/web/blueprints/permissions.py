"""Permissions management page (web permission system, 2026-11-15;
bulk rebuild 2026-11-15; merged with Logger Settings 2026-11-15).

GET  /servers/<gid>/permissions                  -- combined page:
    Permissions tab (rules + unverified role) and Logger Settings
    tab (log channels, event toggles, automod). The page is gated
    on EITHER web:manage_permissions or web:manage_logs; each tab
    is shown only to visitors who hold that tab's gate, and the
    other tab's content is not rendered (or fetched) for them.
    ?tab=permissions (default) or ?tab=logger picks the tab.
POST /servers/<gid>/permissions/add              -- add one rule
POST /servers/<gid>/permissions/add_bulk         -- add many rules at once
POST /servers/<gid>/permissions/remove           -- remove one rule
POST /servers/<gid>/permissions/remove_bulk      -- remove many rules at once
POST /servers/<gid>/permissions/settings         -- set the unverified role

All reads and writes go through the bot-side bridge, so the rules
here are the SAME command_permissions rows Discord /perm manages:
a grant made here works in Discord, and a grant made in Discord
shows up here. Gate for writes: owner bypass (Emily or the guild
owner) or the web:manage_permissions action.
"""

import itertools
import secrets

from flask import (
    Blueprint,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from urllib.parse import quote

from web.blueprints.auth import get_csrf_token
from web.security.decorators import require_web_access, require_web_access_any
from web.services import bridge
from web.services.bridge import BridgeError, BridgeUnavailable
from web.services.web_access import (
    SEEDED_BYPASS_USER_IDS,
    WEB_MANAGE_LOGS,
    WEB_MANAGE_PERMISSIONS,
    clear_permission_cache,
    get_pickable_action_groups,
    get_pickable_actions,
    web_can,
)

try:
    from utils.permissions import is_valid_custom_action_name
except Exception:
    # The website must keep working even if the bot code fails to
    # import: fall back to the same rule the bot uses.
    import re as _re

    _CUSTOM_ACTION_RE = _re.compile(
        r"^(?:web:[a-z0-9_]+|[a-z0-9_-]{1,32})$"
    )

    def is_valid_custom_action_name(name):
        return isinstance(name, str) and bool(
            _CUSTOM_ACTION_RE.match(name)
        )

permissions_api = Blueprint(
    "permissions",
    __name__,
)

# Hard cap on one bulk submit (the bridge enforces the same cap).
MAX_BULK_RULES = 200


def _check_csrf():
    """Accept the header token (JSON callers) or the form field
    (plain form posts on this page). Returns an error string, else
    None."""
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or request.form.get("csrf_token")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return "Invalid CSRF token."
    return None


def _go(gid, notice=None, error=None):
    target = url_for("permissions.page", gid=gid)
    if error:
        return redirect(target + "?error=" + quote(error))
    if notice:
        return redirect(target + "?notice=" + quote(notice))
    return redirect(target)


def _guild_name(gid):
    try:
        guild = bridge.get_guild(int(gid))
        if guild:
            return guild.get("name") or str(gid)
    except Exception:
        pass
    try:
        from web.blueprints.auth import get_user_guilds

        for guild in get_user_guilds() or []:
            if str(guild.get("id")) == str(gid):
                return guild.get("name") or str(gid)
    except Exception:
        pass
    return str(gid)


def _resolve_user_names(gid, user_ids):
    """{user_id: display name} for the given ids, best-effort: a
    lookup that fails (not a member, bot down) just leaves the id
    without a name and the page falls back to the raw id."""
    names = {}
    for uid in sorted({str(u) for u in user_ids}):
        try:
            member = bridge.get_member(gid, uid)
        except Exception:
            member = None
        if not member:
            continue
        name = None
        try:
            name = (
                member.get("display_name")
                or member.get("username")
                or member.get("name")
            )
        except Exception:
            name = None
        if name:
            names[str(uid)] = name
    return names


def _parse_rule_key(value):
    """Parse one "command|target_type|target_id" checkbox value.
    Returns the rule dict, or None when it is malformed."""
    parts = (value or "").split("|")
    if len(parts) != 3:
        return None
    command, target_type, target_id = (p.strip() for p in parts)
    if not command or target_type not in ("role", "user"):
        return None
    if not target_id.isdigit():
        return None
    return {
        "command": command,
        "target_type": target_type,
        "target_id": target_id,
    }


def _target_label(target_type, target_id, role_names, user_names):
    """Friendly name for a target, falling back to the raw id."""
    if target_type == "role":
        return role_names.get(str(target_id)) or str(target_id)
    return user_names.get(str(target_id)) or str(target_id)


@permissions_api.get("/servers/<int:gid>/permissions")
@require_web_access_any(WEB_MANAGE_PERMISSIONS, WEB_MANAGE_LOGS)
def page(gid):
    # Combined Permissions + Logger Settings page. A visitor needs at
    # least one of the two gates; each tab is shown only to visitors
    # who hold that tab's gate (the other tab's content is not
    # rendered and its data is not fetched). Owner bypass sees both.
    can_perms = web_can(WEB_MANAGE_PERMISSIONS, gid)
    can_logs = web_can(WEB_MANAGE_LOGS, gid)
    requested = (request.args.get("tab") or "").strip().lower()
    if requested == "logger" and can_logs:
        active_tab = "logger"
    elif requested == "permissions" and can_perms:
        active_tab = "permissions"
    elif can_perms:
        active_tab = "permissions"
    else:
        active_tab = "logger"

    bridge_error = None
    if can_perms:
        try:
            rules = bridge.list_permission_rules(gid)
        except BridgeUnavailable:
            rules = []
            bridge_error = "Discord bot is not connected -- rules cannot be loaded right now."
        except BridgeError as exc:
            rules = []
            bridge_error = "Could not load rules: %s" % exc.message

        try:
            settings = bridge.get_web_settings(gid)
            unverified_role_id = str(settings.get("unverified_role_id") or "")
        except Exception:
            unverified_role_id = ""

        try:
            roles = bridge.get_roles(gid) or []
        except Exception:
            roles = []
    else:
        rules = []
        roles = []
        unverified_role_id = ""
    role_names = {
        str(r.get("id")): r.get("name")
        for r in roles
        if r.get("id") is not None
    }

    # Bypass users (global list, shown on the Permissions tab).
    # Resolved to display names best-effort, like rule targets.
    bypass_users = []
    if can_perms:
        try:
            bypass_rows = bridge.list_bypass_users()
        except Exception:
            bypass_rows = []
        bypass_names = _resolve_user_names(
            gid, [r.get("user_id") for r in bypass_rows]
        )
        for row in bypass_rows:
            uid = str(row.get("user_id") or "")
            bypass_users.append({
                "user_id": uid,
                "added_by": str(row.get("added_by") or ""),
                "created_at": row.get("created_at") or "",
                "name": bypass_names.get(uid) or "",
                "seeded": uid in SEEDED_BYPASS_USER_IDS,
            })
        bypass_users.sort(key=lambda b: (not b["seeded"], b["name"].casefold() or b["user_id"]))

    rules_sorted = sorted(
        rules,
        key=lambda r: (r.get("command") or "", r.get("target_type") or "",
                       str(r.get("target_id") or "")),
    )
    rule_groups = [
        (command, list(group))
        for command, group in itertools.groupby(
            rules_sorted, key=lambda r: r.get("command") or ""
        )
    ]
    filter_commands = sorted({r.get("command") or "" for r in rules})
    user_names = _resolve_user_names(
        gid,
        [r.get("target_id") for r in rules
         if r.get("target_type") == "user"],
    ) if can_perms else {}

    # Who added each rule, resolved the same way as target user
    # names. Non-digit creator values are legacy free text (e.g.
    # "poos241 (Purekush)") -- already a name, shown as-is.
    created_by_names = _resolve_user_names(
        gid,
        [r.get("created_by") for r in rules
         if str(r.get("created_by") or "").isdigit()],
    ) if can_perms else {}

    return render_template(
        "permissions.html",
        guild_id=gid,
        guild_name=_guild_name(gid),
        rules=rules_sorted,
        rule_groups=rule_groups,
        filter_commands=filter_commands,
        role_names=role_names,
        user_names=user_names,
        created_by_names=created_by_names,
        roles=sorted(
            ({"id": str(r.get("id")), "name": r.get("name")}
             for r in roles if r.get("id") is not None),
            key=lambda r: (r["name"] or "").casefold(),
        ),
        pickable_actions=get_pickable_actions() if can_perms else [],
        action_groups=get_pickable_action_groups() if can_perms else [],
        bypass_users=bypass_users,
        seeded_bypass_ids=sorted(SEEDED_BYPASS_USER_IDS),
        unverified_role_id=unverified_role_id,
        unverified_role_name=role_names.get(unverified_role_id),
        notice=request.args.get("notice", ""),
        error=request.args.get("error", "") or bridge_error or "",
        can_perms=can_perms,
        can_logs=can_logs,
        active_tab=active_tab,
    )


@permissions_api.post("/servers/<int:gid>/permissions/add")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def add_rule(gid):
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    command = (request.form.get("command") or "").strip()
    target_type = (request.form.get("target_type") or "").strip()
    if target_type == "role":
        target_id = (request.form.get("role_id") or "").strip()
    else:
        target_id = (request.form.get("user_id") or "").strip()
    allowed = (request.form.get("allowed") or "allow") == "allow"

    pickable = {name for name, _ in get_pickable_actions()}
    if not command or (
        command not in pickable
        and not is_valid_custom_action_name(command)
    ):
        return _go(
            gid,
            error="Pick a valid action/command, or type a custom "
                  "action name (lowercase letters, digits, "
                  "underscores; web keys start with web:).",
        )
    if target_type not in ("role", "user"):
        return _go(gid, error="Target must be a role or a user.")
    if not target_id.isdigit():
        return _go(gid, error="Target ID must be a Discord ID (digits only).")

    user = session.get("user") or {}
    created_by = str(user.get("id") or "")
    try:
        bridge.add_permission_rule(
            gid, command, target_type, target_id, allowed, created_by
        )
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- rule not saved.")
    except BridgeError as exc:
        return _go(gid, error="Could not save rule: %s" % exc.message)

    # The admin's own new grant takes effect immediately in this
    # session instead of waiting out the 5-minute permission cache.
    clear_permission_cache(gid)
    return _go(
        gid,
        notice="Rule saved: %s for %s %s (%s)."
        % (
            command,
            target_type,
            target_id,
            "allow" if allowed else "deny",
        ),
    )


@permissions_api.post("/servers/<int:gid>/permissions/add_bulk")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def add_rules_bulk(gid):
    """Add many rules in one submit: every selected target x every
    selected action, all with the same allow/deny. The bridge
    creates the whole batch in one call and reports how many were
    created, updated (same target, different allow/deny), or
    skipped (identical rule already existed)."""
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    role_ids = request.form.getlist("role_ids")
    user_ids_raw = request.form.get("user_ids") or ""
    commands = request.form.getlist("commands")
    custom_action = (request.form.get("custom_action") or "").strip()
    allowed = (request.form.get("allowed") or "allow") == "allow"

    # A hand-typed action for a command/key that is not in the
    # picker. It must be a well-formed name; anything else is
    # rejected and nothing is created.
    if custom_action:
        if not is_valid_custom_action_name(custom_action):
            return _go(
                gid,
                error="That custom action name is not valid: %s. "
                      "Use lowercase letters, digits, and "
                      "underscores (a web key starts with web:), "
                      "no spaces or other characters." % custom_action,
            )
        if custom_action not in commands:
            commands = commands + [custom_action]

    pickable = {name for name, _ in get_pickable_actions()}
    bad_commands = [c for c in commands if c not in pickable
                    and not is_valid_custom_action_name(c)]
    if bad_commands:
        return _go(gid, error="Unknown action(s): %s."
                    % ", ".join(bad_commands[:5]))

    # Roles must be real guild roles -- a stale checkbox value is
    # dropped instead of creating a rule for a role that is gone.
    try:
        roles = bridge.get_roles(gid) or []
    except Exception:
        roles = []
    role_names = {
        str(r.get("id")): r.get("name")
        for r in roles
        if r.get("id") is not None
    }
    role_ids = [r for r in dict.fromkeys(role_ids)
                if r.isdigit() and r in role_names]

    user_ids = [line.strip() for line in user_ids_raw.splitlines()]
    user_ids = [u for u in dict.fromkeys(user_ids) if u]
    bad_users = [u for u in user_ids if not u.isdigit()]
    if bad_users:
        return _go(gid, error="These user IDs are not digits: %s."
                    % ", ".join(bad_users[:5]))

    targets = ([("role", rid) for rid in role_ids]
               + [("user", uid) for uid in user_ids])
    if not targets:
        return _go(gid, error="Pick at least one role or paste at "
                    "least one user ID.")
    if not commands:
        return _go(gid, error="Pick at least one action.")

    rules = [
        {"command": command, "target_type": target_type,
         "target_id": target_id, "allowed": allowed}
        for target_type, target_id in targets
        for command in commands
    ]
    if len(rules) > MAX_BULK_RULES:
        return _go(gid, error="That batch is %d rules -- at most %d "
                    "at a time." % (len(rules), MAX_BULK_RULES))

    user = session.get("user") or {}
    created_by = str(user.get("id") or "")
    try:
        result = bridge.add_permission_rules_bulk(gid, rules, created_by)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- rules not saved.")
    except BridgeError as exc:
        return _go(gid, error="Could not save rules: %s" % exc.message)

    created = int(result.get("created") or 0)
    updated = int(result.get("updated") or 0)
    skipped = int(result.get("skipped") or 0)

    user_names = _resolve_user_names(
        gid, [tid for ttype, tid in targets if ttype == "user"])
    target_labels = [
        _target_label(ttype, tid, role_names, user_names)
        for ttype, tid in targets
    ]
    target_summary = ", ".join(target_labels)
    action_summary = ", ".join(commands)
    direction = "allow" if allowed else "deny"

    clear_permission_cache(gid)
    if created == 0 and updated == 0:
        return _go(
            gid,
            notice="Nothing new -- all %d rule(s) already existed "
                   "(%s for %s, %s)."
                   % (skipped, action_summary, target_summary, direction),
        )
    bits = []
    if created:
        bits.append("created %d" % created)
    if updated:
        bits.append("updated %d (allow/deny changed)" % updated)
    if skipped:
        bits.append("skipped %d (already existed)" % skipped)
    return _go(
        gid,
        notice="Saved %d rule(s) for %s -- %s (%s): %s."
               % (created + updated, target_summary, action_summary,
                  direction, ", ".join(bits)),
    )


@permissions_api.post("/servers/<int:gid>/permissions/remove")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def remove_rule(gid):
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    command = (request.form.get("command") or "").strip()
    target_type = (request.form.get("target_type") or "").strip()
    target_id = (request.form.get("target_id") or "").strip()
    if not command or target_type not in ("role", "user") or not target_id.isdigit():
        return _go(gid, error="Invalid rule to remove.")

    try:
        bridge.delete_permission_rule(gid, command, target_type, target_id)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- rule not removed.")
    except BridgeError as exc:
        return _go(gid, error="Could not remove rule: %s" % exc.message)

    clear_permission_cache(gid)
    return _go(gid, notice="Rule removed: %s for %s %s." % (command, target_type, target_id))


@permissions_api.post("/servers/<int:gid>/permissions/remove_bulk")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def remove_rules_bulk(gid):
    """Remove every checked rule in one submit."""
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    parsed = []
    for value in request.form.getlist("rule_keys"):
        item = _parse_rule_key(value)
        if item is not None:
            parsed.append(item)
    if not parsed:
        return _go(gid, error="Select at least one rule to remove.")

    try:
        result = bridge.delete_permission_rules_bulk(gid, parsed)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- rules not removed.")
    except BridgeError as exc:
        return _go(gid, error="Could not remove rules: %s" % exc.message)

    deleted = int(result.get("deleted") or 0)
    clear_permission_cache(gid)
    if deleted == len(parsed):
        return _go(gid, notice="Removed %d rule(s)." % deleted)
    return _go(
        gid,
        notice="Removed %d of %d selected rule(s) -- the rest were "
               "already gone." % (deleted, len(parsed)),
    )


@permissions_api.post("/servers/<int:gid>/permissions/settings")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def save_settings(gid):
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    role_id = (request.form.get("unverified_role_id") or "").strip()
    if role_id and not role_id.isdigit():
        return _go(gid, error="Unverified role ID must be digits only (or empty to clear it).")

    try:
        bridge.set_web_settings(gid, role_id)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- setting not saved.")
    except BridgeError as exc:
        return _go(gid, error="Could not save setting: %s" % exc.message)

    if role_id:
        return _go(gid, notice="Unverified role set to %s." % role_id)
    return _go(gid, notice="Unverified role cleared.")


@permissions_api.post("/servers/<int:gid>/permissions/bypass/add")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def add_bypass_user_route(gid):
    """Add one user to the global bypass list (they may open any
    guild's site without needing any permission)."""
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    user_id = (request.form.get("user_id") or "").strip()
    if not user_id.isdigit():
        return _go(gid, error="Bypass user ID must be a Discord ID (digits only).")

    user = session.get("user") or {}
    added_by = str(user.get("id") or "")
    try:
        bridge.add_bypass_user(user_id, added_by)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- bypass user not saved.")
    except BridgeError as exc:
        return _go(gid, error="Could not save bypass user: %s" % exc.message)

    clear_permission_cache(gid)
    return _go(gid, notice="Bypass user added: %s." % user_id)


@permissions_api.post("/servers/<int:gid>/permissions/bypass/remove")
@require_web_access(WEB_MANAGE_PERMISSIONS)
def remove_bypass_user_route(gid):
    """Remove one user from the global bypass list. The two seeded
    (permanent) bypass users cannot be removed."""
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(gid, error=csrf_error)

    user_id = (request.form.get("user_id") or "").strip()
    if not user_id.isdigit():
        return _go(gid, error="Bypass user ID must be a Discord ID (digits only).")
    if user_id in SEEDED_BYPASS_USER_IDS:
        return _go(
            gid,
            error="That user is a permanent bypass user and cannot "
                  "be removed.",
        )

    try:
        bridge.remove_bypass_user(user_id)
    except BridgeUnavailable:
        return _go(gid, error="Discord bot is not connected -- bypass user not removed.")
    except BridgeError as exc:
        return _go(gid, error="Could not remove bypass user: %s" % exc.message)

    clear_permission_cache(gid)
    return _go(gid, notice="Bypass user removed: %s." % user_id)
