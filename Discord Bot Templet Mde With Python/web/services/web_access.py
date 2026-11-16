"""Website-side access control for the web permission system.

The bot is the source of truth: every guild page load asks the bot
(bridge ``/web_access`` endpoint) whether the logged-in user may
enter the guild and whether they hold a given action. The decision
uses the SAME ``command_permissions`` rows Discord ``/perm`` manages,
so a grant made in Discord and a grant made on the website's
permissions page are the same grant.

Check order (enforced by ``check_web_access`` and both decorators):
  1. Owner bypass -- Emily (287282266261159937) or the Little Haven
     owner (762550157765902356), or the guild owner, always gets in,
     no bridge call needed.
  2. Membership -- the bridge says the user is not a member.
  3. Unverified -- the member still holds the guild's unverified
     role (RaidProtect removes it when the captcha is solved).
  4. Permission -- the requested action is not granted.

Caching rule (required, and the reason this module exists):
  * The permission booleans MAY be cached in the Flask session for
    up to 5 minutes (PERMISSION_CACHE_TTL_S).
  * The unverified flag must be re-checked FRESH on every guild page
    load: the bridge is called fresh every time for the
    member/bypass/unverified fields, and only the permission booleans
    are taken from the cache when it is still within TTL. So a user
    who just solved the captcha gets in on their very next page load,
    while a permission grant/revoke takes at most 5 minutes to show
    up on the website (Discord itself is immediate).

Fail closed: any bridge failure raises BridgeUnavailable and the
decorators answer "unavailable" (page) / 503 (API) instead of
letting anyone in.
"""

from __future__ import annotations

import time

from flask import g, session

from web.services import bridge
from web.services.bridge import BridgeUnavailable

EMILY_ID = "287282266261159937"

# The website bypass is EXACTLY these two user ids, in addition to
# the guild owner of whichever guild is being checked. The second
# OWNER_IDS entry (765094342279954509) matches neither guild owner
# and must NOT bypass -- do not widen this set without Emily's
# say-so. This list is web-only: it does not change what OWNER_IDS
# means for Discord. Mirrors _WEB_BYPASS_USER_IDS in bridge_api.py.
WEB_BYPASS_USER_IDS = frozenset({
    EMILY_ID,
    "762550157765902356",  # Little Haven owner
})

# The two seeded bypass ids, mirrored from
# data.DB.Storage.storage.SEEDED_BYPASS_USER_IDS. They are the
# permanent bypass floor: they always bypass (here and on the bot
# side) and the permissions page refuses to remove them.
SEEDED_BYPASS_USER_IDS = frozenset({
    EMILY_ID,
    "762550157765902356",  # Little Haven owner
})

# Permission booleans may be reused from the session cache for this long.
PERMISSION_CACHE_TTL_S = 300

_CACHE_KEY = "web_perm_cache"

# ----------------------------------------------------------------------
# Web-only action keys (no Discord slash command). Custom rules in
# command_permissions can grant them like any Discord command; with
# no custom rules the bot falls back to admin-only, except
# web:view_dashboard which falls back to the old moderator tier.
# ----------------------------------------------------------------------
WEB_VIEW_DASHBOARD = "web:view_dashboard"
WEB_MANAGE_LOGS = "web:manage_logs"
WEB_MANAGE_PERMISSIONS = "web:manage_permissions"
WEB_MANAGE_NOTES = "web:manage_notes"
WEB_WIPE_MEMBER = "web:wipe_member"

# Per-section view keys (2026-11-16): one per major site section.
# A user may open a section only if they hold its key (or owner
# bypass). No-rules default is the moderator tier, same as
# web:view_dashboard (set on the bot side in
# utils/permissions.py _WEB_ONLY_DEFAULTS).
WEB_VIEW_MEMBERS = "web:view_members"
WEB_VIEW_LEADERBOARD = "web:view_leaderboard"
WEB_VIEW_CHANNELS = "web:view_channels"
WEB_VIEW_ROLES = "web:view_roles"
WEB_VIEW_LOGGER = "web:view_logger"
WEB_VIEW_ACTIVITY = "web:view_activity"
WEB_VIEW_VOICE = "web:view_voice"

WEB_VIEW_SECTIONS = (
    WEB_VIEW_MEMBERS,
    WEB_VIEW_LEADERBOARD,
    WEB_VIEW_CHANNELS,
    WEB_VIEW_ROLES,
    WEB_VIEW_LOGGER,
    WEB_VIEW_ACTIVITY,
    WEB_VIEW_VOICE,
)

WEB_ONLY_ACTIONS = (
    WEB_VIEW_DASHBOARD,
    WEB_MANAGE_LOGS,
    WEB_MANAGE_PERMISSIONS,
    WEB_MANAGE_NOTES,
    WEB_WIPE_MEMBER,
    WEB_VIEW_MEMBERS,
    WEB_VIEW_LEADERBOARD,
    WEB_VIEW_CHANNELS,
    WEB_VIEW_ROLES,
    WEB_VIEW_LOGGER,
    WEB_VIEW_ACTIVITY,
    WEB_VIEW_VOICE,
)

WEB_ONLY_ACTION_DESCRIPTIONS = {
    WEB_VIEW_DASHBOARD: (
        "View a server's dashboard, members, channels, leaderboard, "
        "roles, and other read-only pages."
    ),
    WEB_MANAGE_LOGS: (
        "View the Logger history and change logger settings "
        "(channels, toggles, automod)."
    ),
    WEB_MANAGE_PERMISSIONS: (
        "Manage this website's permission rules and the unverified "
        "role for a server."
    ),
    WEB_MANAGE_NOTES: (
        "Add or delete moderator notes on a member (web-only; no "
        "Discord command)."
    ),
    WEB_WIPE_MEMBER: (
        "Wipe a member's website data (warns, notes, cases, XP, "
        "watch, ban, timeout). Web-only; no Discord command."
    ),
    WEB_VIEW_MEMBERS: (
        "Open the Members section (member list, member details). "
        "A person also needs web:view_dashboard to enter the site."
    ),
    WEB_VIEW_LEADERBOARD: (
        "Open the Leaderboard section. A person also needs "
        "web:view_dashboard to enter the site."
    ),
    WEB_VIEW_CHANNELS: (
        "Open the Channels section (channel list and channel "
        "details). A person also needs web:view_dashboard to enter "
        "the site."
    ),
    WEB_VIEW_ROLES: (
        "Open the Roles section (role list and role details). A "
        "person also needs web:view_dashboard to enter the site."
    ),
    WEB_VIEW_LOGGER: (
        "Open the Logger section (event history, live feed, "
        "analytics). Logger SETTINGS still need web:manage_logs. A "
        "person also needs web:view_dashboard to enter the site."
    ),
    WEB_VIEW_ACTIVITY: (
        "Open the Activity section (activity feed and event "
        "details). A person also needs web:view_dashboard to enter "
        "the site."
    ),
    WEB_VIEW_VOICE: (
        "Open the Voice section (live voice viewer). A person also "
        "needs web:view_dashboard to enter the site."
    ),
}

# ----------------------------------------------------------------------
# Action -> route mapping (the website's actual actions).
#
# Discord-command keys map 1:1 to the grantable command of the same
# name in utils/permissions.py GRANTABLE_COMMANDS. Web-only keys are
# listed above. Actions the website does NOT have (bot_settings and
# level_settings have no web page) are deliberately absent here.
# ----------------------------------------------------------------------
# Read-only guild pages and APIs.
VIEW_ACTIONS = (WEB_VIEW_DASHBOARD,)
# Logger viewing + settings.
LOG_ACTIONS = (WEB_MANAGE_LOGS,)

# Every action the website gates on, with a short description of what
# it guards. Used by the permissions page picker and SUMMARY-web.md.
ACTION_DESCRIPTIONS = {
    # Discord commands (descriptions mirror utils/permissions.py).
    "timeout": "Time out a member, or remove a timeout.",
    "kick": "Kick a member.",
    "ban": "Ban a member, unban, or temp-ban.",
    "warn": "Warn a member.",
    "clear_user": "Clear a user's messages.",
    "rename_user": "Change a user's nickname.",
    "remove_user_role": "Strip all roles from a user.",
    "add_xp": "Add or remove XP for a user.",
    "watch_add": "Add a user to the watch list.",
    "watch_remove": "Remove a user from the watch list.",
    "backup_now": "Take a backup snapshot right now.",
    "backup_status": "View the backup snapshots page.",
    WEB_VIEW_DASHBOARD: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_DASHBOARD],
    WEB_MANAGE_LOGS: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_MANAGE_LOGS],
    WEB_MANAGE_PERMISSIONS: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_MANAGE_PERMISSIONS],
    WEB_MANAGE_NOTES: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_MANAGE_NOTES],
    WEB_WIPE_MEMBER: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_WIPE_MEMBER],
    WEB_VIEW_MEMBERS: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_MEMBERS],
    WEB_VIEW_LEADERBOARD: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_LEADERBOARD],
    WEB_VIEW_CHANNELS: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_CHANNELS],
    WEB_VIEW_ROLES: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_ROLES],
    WEB_VIEW_LOGGER: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_LOGGER],
    WEB_VIEW_ACTIVITY: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_ACTIVITY],
    WEB_VIEW_VOICE: WEB_ONLY_ACTION_DESCRIPTIONS[WEB_VIEW_VOICE],
}


def get_pickable_actions():
    """(action, description) list for the permissions page picker.

    The grantable Discord commands, straight from the bot's own
    list, plus the web-only keys. Falls back to the actions the
    website itself gates on when the bot list cannot be imported
    (the website process must keep working even if the bot code
    fails to import).
    """
    items = []
    try:
        from utils.permissions import GRANTABLE_COMMANDS

        items = [(name, desc) for name, desc in GRANTABLE_COMMANDS]
    except Exception:
        items = [
            (name, ACTION_DESCRIPTIONS.get(name, name))
            for name in sorted(ACTION_DESCRIPTIONS)
            if not name.startswith("web:")
        ]
    seen = {name for name, _ in items}
    for action in WEB_ONLY_ACTIONS:
        if action not in seen:
            items.append(
                (action, WEB_ONLY_ACTION_DESCRIPTIONS[action])
            )
    return items


# ----------------------------------------------------------------------
# Pickable actions, grouped for the bulk form on the permissions page.
# Discord commands first (in family groups, in a fixed order), then
# the website-only keys. Unknown future grantable commands land in
# "Moderation" so they still show up instead of vanishing.
# ----------------------------------------------------------------------
_ACTION_FAMILY_ORDER = (
    "Moderation",
    "Ban log",
    "Levels & XP",
    "Custom badges",
    "Automod",
    "Lockdown",
    "Backups",
    "Tickets",
    "Mod logs",
    "Introductions",
    "Watch list",
    "Appeals & mod notes",
    "Question of the day",
    "Website sections",
    "Website-only actions",
)

_LEVEL_COMMANDS = frozenset({
    "add_xp", "resetxp", "cleardata", "set_xp_rate", "set_cooldown",
    "set_level_channel", "set_spam_channel", "set_level_role",
    "remove_level_role", "set_levelup_message", "toggle_no_xp",
    "no_xp_bulk", "bot_settings", "toggle_levels", "level_settings",
    "xp_event", "xp_event_end",
})

def _action_family(name):
    """Family label for one pickable action/command name."""
    if name in WEB_VIEW_SECTIONS:
        return "Website sections"
    if name.startswith("web:"):
        return "Website-only actions"
    if name.startswith("banlog_"):
        return "Ban log"
    if name.startswith("badge_"):
        return "Custom badges"
    if name.startswith("automod_"):
        return "Automod"
    if name.startswith("lockdown_"):
        return "Lockdown"
    if name.startswith("ticket_"):
        return "Tickets"
    if name.startswith("modlogs_"):
        return "Mod logs"
    if name.startswith("intro_"):
        return "Introductions"
    if name.startswith("watch_"):
        return "Watch list"
    if name.startswith("appeal_") or name == "modnotes_search":
        return "Appeals & mod notes"
    if name.startswith("qotd_"):
        return "Question of the day"
    if name.startswith("backup_"):
        return "Backups"
    if name in _LEVEL_COMMANDS:
        return "Levels & XP"
    return "Moderation"


def get_pickable_action_groups():
    """[(family label, [(action, description), ...]), ...] for the
    permissions page bulk form. Same pickable set as
    get_pickable_actions(), just grouped."""
    grouped = {}
    for name, desc in get_pickable_actions():
        grouped.setdefault(_action_family(name), []).append((name, desc))
    return [
        (family, grouped[family])
        for family in _ACTION_FAMILY_ORDER
        if family in grouped
    ]


# ----------------------------------------------------------------------
# Bypass
# ----------------------------------------------------------------------

def _stored_bypass_user_ids():
    """Set of user ids on the stored bypass list (editable on the
    permissions page). Read from the website's own DB connection.
    Returns an empty set when the DB cannot be read -- the hardcoded
    floor above still applies, so a DB outage never locks Emily or
    the LH owner out."""
    try:
        from data.DB.Storage.storage import get_bypass_user_ids
        from web.services.local_loop import run_async

        return set(run_async(get_bypass_user_ids(), timeout=10))
    except Exception:
        return set()


def is_owner_bypass(guild_id) -> bool:
    """True when the session user is Emily, the Little Haven owner,
    on the stored bypass list, or the guild owner.

    Local only (explicit id list + stored list + OAuth guild list),
    no bridge call. The bot-side endpoint computes the same bypass
    from the same sources plus the guild owner id, so a bypass the
    website grants locally is one the bot agrees with.
    """
    user = session.get("user") or {}
    uid = str(user.get("id") or "")
    if not uid:
        return False
    if uid in WEB_BYPASS_USER_IDS:
        return True
    if uid in _stored_bypass_user_ids():
        return True
    try:
        from web.services.permissions import is_guild_owner

        return bool(is_guild_owner(guild_id))
    except Exception:
        return False


# ----------------------------------------------------------------------
# Session permission cache (booleans only, 5-minute TTL)
# ----------------------------------------------------------------------

def _cache_read(guild_id):
    """(fetched_at, {action: bool}) for this guild, or (0, {})."""
    try:
        entry = (session.get(_CACHE_KEY) or {}).get(str(guild_id)) or {}
        return float(entry.get("fetched_at") or 0), dict(
            entry.get("perms") or {}
        )
    except Exception:
        return 0.0, {}


def _cache_write(guild_id, perms):
    """Merge fresh permission booleans into the session cache."""
    try:
        cache = dict(session.get(_CACHE_KEY) or {})
        fetched_at, stored = _cache_read(guild_id)
        stored.update({str(k): bool(v) for k, v in (perms or {}).items()})
        cache[str(guild_id)] = {
            "fetched_at": time.time(),
            "perms": stored,
        }
        session[_CACHE_KEY] = cache
    except Exception:
        pass


def clear_permission_cache(guild_id=None):
    """Drop the cached permission booleans (tests / logout)."""
    try:
        if guild_id is None:
            session.pop(_CACHE_KEY, None)
        else:
            cache = dict(session.get(_CACHE_KEY) or {})
            cache.pop(str(guild_id), None)
            session[_CACHE_KEY] = cache
    except Exception:
        pass


# ----------------------------------------------------------------------
# Fresh access check
# ----------------------------------------------------------------------

def get_web_access(guild_id, actions):
    """Fresh access decision for one guild.

    Always calls the bridge fresh for the member/bypass/unverified
    fields. The permission booleans come from the session cache when
    it is within TTL and covers every requested action; otherwise
    the fresh bridge values are used and cached.

    Returns {"is_bypass", "is_member", "is_unverified",
    "unverified_role_id", "member", "permissions": {action: bool}}.

    Raises BridgeUnavailable when the bot cannot be reached (fail
    closed -- callers answer "unavailable" / 503).
    """
    actions = [str(a) for a in (actions or [])]
    user = session.get("user") or {}
    uid = str(user.get("id") or "")

    if is_owner_bypass(guild_id):
        return {
            "is_bypass": True,
            "is_member": True,
            "is_unverified": False,
            "unverified_role_id": "",
            "member": {"id": uid, "roles": []},
            "permissions": {action: True for action in actions},
        }

    # Fresh bridge call every time: member, bypass, and unverified
    # are never taken from a cache.
    #
    # One exception, scoped to this single request: a page render
    # calls get_web_access repeatedly (the gate, then one web_can
    # per button). Repeating the bridge call inside the same request
    # adds nothing -- the member/unverified answers cannot change
    # mid-render -- so the result is memoised on flask.g for the
    # rest of this request only. The next page load calls the bridge
    # fresh again, which is what the unverified rule requires. When
    # a later call in the same request asks for actions the memo
    # does not cover, one more bridge call fetches just those.
    try:
        memo = getattr(g, "_web_access_memo", None)
    except Exception:
        memo = None
    if memo is None:
        memo = {}
        try:
            g._web_access_memo = memo
        except Exception:
            pass
    memo_entry = memo.get(str(guild_id))
    if memo_entry is not None and all(
        action in memo_entry["permissions"] for action in actions
    ):
        return dict(memo_entry)
    payload = bridge.get_web_access(guild_id, uid, actions)
    member = payload.get("member")
    is_bypass = bool(payload.get("is_bypass"))
    is_unverified = bool(payload.get("is_unverified"))
    fresh_perms = {
        str(k): bool(v)
        for k, v in (payload.get("permissions") or {}).items()
    }

    if is_bypass:
        permissions = {action: True for action in actions}
    else:
        fetched_at, cached = _cache_read(guild_id)
        fresh_cache = (
            time.time() - fetched_at < PERMISSION_CACHE_TTL_S
            and all(action in cached for action in actions)
        )
        if fresh_cache:
            # Reuse the cached decision; the fresh bridge values are
            # ignored until the TTL expires.
            permissions = {action: bool(cached[action]) for action in actions}
        else:
            permissions = {
                action: bool(fresh_perms.get(action, False))
                for action in actions
            }
            _cache_write(guild_id, fresh_perms)

    result = {
        "is_bypass": is_bypass,
        "is_member": member is not None,
        "is_unverified": is_unverified,
        "unverified_role_id": str(payload.get("unverified_role_id") or ""),
        "member": member,
        "permissions": permissions,
    }
    if memo_entry is not None:
        merged = dict(memo_entry)
        merged["permissions"] = {
            **memo_entry.get("permissions", {}),
            **permissions,
        }
        memo[str(guild_id)] = merged
        return dict(merged)
    memo[str(guild_id)] = result
    return dict(result)


def check_web_access(guild_id, action):
    """None when the session user may do ``action`` in the guild,
    else the block reason: "not_member" | "unverified" |
    "permission". Raises BridgeUnavailable when the bot is down."""
    access = get_web_access(guild_id, [action])
    if access["is_bypass"]:
        return None
    if not access["is_member"]:
        return "not_member"
    if access["is_unverified"]:
        return "unverified"
    if not access["permissions"].get(action):
        return "permission"
    return None


def can_enter_guild(guild_id):
    """(can_enter, blocked_reason) for the guild dashboard.

    ``blocked_reason`` is None when the user may enter, else one of
    "not_member" | "unverified" | "permission" | "unavailable"
    (bot unreachable -- fail closed).
    """
    try:
        reason = check_web_access(guild_id, WEB_VIEW_DASHBOARD)
    except BridgeUnavailable:
        return False, "unavailable"
    except Exception:
        return False, "unavailable"
    return reason is None, reason


def has_web_action_anywhere(action):
    """True when the session user may do ``action`` in at least one
    guild the bot is in. Used by bot-wide pages with no guild in the
    URL (backups). Fail closed: bridge failures count as "no"."""
    try:
        guild_ids = bridge.get_bot_guild_ids()
    except Exception:
        return False
    for gid in guild_ids:
        try:
            if is_owner_bypass(gid):
                return True
            if check_web_access(gid, action) is None:
                return True
        except Exception:
            continue
    return False


def web_can(action, guild_id=None):
    """Template helper: True when the session user may do ``action``
    in ``guild_id`` (defaults to the selected guild). Fail closed.

    Fetches the whole page-action set in one bridge call (memoised
    for the rest of this request by get_web_access), so a template
    with a dozen buttons costs one extra bridge call, not twelve.
    """
    gid = guild_id or session.get("selected_guild_id")
    if not gid:
        return False
    try:
        access = get_web_access(gid, list(PAGE_ACTIONS))
        if access["is_bypass"]:
            return True
        if not access["is_member"] or access["is_unverified"]:
            return False
        return bool(access["permissions"].get(action, False))
    except Exception:
        return False


# Actions a guild page's buttons can ask web_can() about. Fetched as
# one set so a template with many buttons costs a single bridge call
# per page load (the decorator's own call covers web:view_dashboard
# first; this set covers the rest).
PAGE_ACTIONS = (
    "warn",
    "timeout",
    "kick",
    "ban",
    "clear_user",
    "web:manage_notes",
    "watch_add",
    "watch_remove",
    "add_xp",
    "rename_user",
    "remove_user_role",
    "web:wipe_member",
    "web:view_dashboard",
    "web:manage_logs",
    "web:manage_permissions",
    "web:view_members",
    "web:view_leaderboard",
    "web:view_channels",
    "web:view_roles",
    "web:view_logger",
    "web:view_activity",
    "web:view_voice",
)
