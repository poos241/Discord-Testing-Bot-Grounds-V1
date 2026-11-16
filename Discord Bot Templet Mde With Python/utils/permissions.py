"""Custom per-command permissions.

Lets a server admin grant a role (or one user, for training) access to a
specific bot action -- a slash command or a panel button -- without
turning on Discord's Administrator permission for that role.

How it works
------------
* Rules live in the ``command_permissions`` table (shared SQLite db), one
  row per grant: guild, command/action name, target type (role or user),
  target id, and allow (1) or deny (0).
* When someone uses a command or button, the bot checks, in order:
  1. Server admins (Discord Administrator) always get in. Safety net.
  2. A user-level DENY for that command wins over everything else.
  3. A user-level ALLOW wins over role rules (the training override).
  4. A role-level DENY on any of the user's roles wins over role allows.
  5. A role-level ALLOW on any of the user's roles lets them in.
  6. If the command has NO custom rules at all, fall back to the
     command's normal Discord permission check (unchanged behaviour).
  7. If custom rules exist but nothing matches the user, deny (the
     custom rules replace the Discord check).
* The website reads the same table straight from the database file, so
  it can enforce these rules even while the bot is offline (that part
  is a later step -- this module is the bot-side check).

The grantable actions are the moderation actions and the ban-log
commands. Add more here (name + short description) and they become
pickable in /perm allow, /perm remove, and /perm list. The command
picker is an autocomplete (capped at 25 results per query), so the
list itself is not capped -- only each bulk/picker group is.
"""

import re

from data.DB.Storage.storage import get_command_permissions

# (action name, description shown in the setup commands)
GRANTABLE_COMMANDS = [
    ("ban", "Ban a member (panel Ban button)"),
    ("kick", "Kick a member (panel Kick button)"),
    ("timeout", "Time out a member (panel button + /timeout)"),
    ("warn", "Warn a member (panel Warn button)"),
    ("clear_user", "Clear a user's messages (/clear_user)"),
    ("banlog_log", "Post a ban/kick log to GitHub (/banlog log)"),
    ("banlog_approve", "Approve a GitHub log (/banlog log approve)"),
    ("banlog_update", "Update a GitHub log (/banlog log update)"),
    ("banlog_collect", "Collect screenshots for a log (/banlog log collect)"),
    ("banlog_delete", "Delete a GitHub log (/banlog log delete)"),
    ("banlog_backfill_cases", "Backfill case numbers (/banlog log backfill_cases)"),
    ("banlog_set_channel", "Set the evidence channel (/banlog log set_channel)"),
    # Level / XP admin commands (Level_system.py). These are powerful --
    # cleardata wipes all level data for the server -- so only grant
    # them to roles you trust. The admin decides who gets what.
    ("add_xp", "Add XP to a user (/add_xp)"),
    ("resetxp", "Reset XP and level for a user (/resetxp)"),
    ("cleardata", "Clear all level data for this server (/cleardata)"),
    ("set_xp_rate", "Set XP gain range per message (/set_xp_rate)"),
    ("set_cooldown", "Set XP gain cooldown (/set_cooldown)"),
    ("set_level_channel", "Set level-up message channel (/set_level_channel)"),
    ("set_spam_channel", "Set the channel where /level works (/set_spam_channel)"),
    ("set_level_role", "Set a role reward for reaching a level (/set_level_role)"),
    ("remove_level_role", "Remove a level role reward (/remove_level_role)"),
    ("set_levelup_message", "Set a custom level-up message (/set_levelup_message)"),
    ("toggle_no_xp", "Toggle XP gains in a channel (/toggle_no_xp)"),
    ("no_xp_bulk", "Turn XP off/on in many channels at once (/no_xp_bulk)"),
    ("bot_settings", "Show every bot system's on/off state and config (/bot_settings)"),
    ("toggle_levels", "Turn the level system on/off (/toggle_levels)"),
    ("level_settings", "Show the level system's full configuration (/level_settings)"),
    ("xp_event", "Start a bonus XP event (/xp_event)"),
    ("xp_event_end", "End the bonus XP event early (/xp_event_end)"),
    # Admin panel / role commands (admin_cog.py).
    ("userinfo", "View detailed info about a user (/userinfo)"),
    ("add_user_role", "Give a role to a user (/add_user_role)"),
    ("remove_user_role", "Remove a role from a user (/remove_user_role)"),
    ("rename_bot", "Change the bot's name in this server (/rename_bot)"),
    ("rename_user", "Change a user's name in this server (/rename_user)"),
    ("reset_user_name", "Reset a user's name (/reset_user_name)"),
    ("timeout_board", "Manage the Active Timeouts board (/timeout_board)"),
    # Custom badges (CustomBadges.py, group /badge).
    ("badge_create", "Create a custom badge (/badge create)"),
    ("badge_award", "Award a custom badge (/badge award)"),
    ("badge_remove", "Remove a custom badge from a user (/badge remove)"),
    ("badge_delete", "Delete a custom badge (/badge delete)"),
    ("badge_list", "List custom badges (/badge list)"),
    # Automod (Automod.py, group /automod).
    ("automod_status", "Show automod rules and spam settings (/automod status)"),
    ("automod_toggle", "Turn one automod rule on or off (/automod toggle)"),
    ("automod_config", "Set the spam burst threshold and window (/automod config)"),
    # Lockdown (Lockdown.py, group /lockdown).
    ("lockdown_lock", "Lock a channel (/lockdown lock)"),
    ("lockdown_unlock", "Unlock a channel (/lockdown unlock)"),
    ("lockdown_lockall", "Lock every text channel (/lockdown lockall)"),
    ("lockdown_unlockall", "Unlock every channel the bot locked (/lockdown unlockall)"),
    ("lockdown_slowmode", "Set slowmode on a channel (/lockdown slowmode)"),
    ("lockdown_status", "Show locked channels and pending auto-unlocks (/lockdown status)"),
    # Backups (Backup.py, group /backup).
    ("backup_now", "Take a backup snapshot right now (/backup now)"),
    ("backup_status", "Show the latest backup snapshot (/backup status)"),
    # Tickets (Tickets.py, group /ticket) -- panel/config/show/list only.
    # open/close/reopen/claim/delete/add/remove are ticket-flow
    # (opener-or-staff) and keep their own checks.
    ("ticket_panel", "Post the ticket panel in this channel (/ticket panel)"),
    ("ticket_config", "Set the ticket settings (/ticket config)"),
    ("ticket_show", "Show the ticket settings (/ticket show)"),
    ("ticket_list", "List this server's open tickets (/ticket list)"),
    # Modlogs (Modlogs.py).
    ("modlogs_list", "Show moderation cases (/modlogs list)"),
    ("modlogs_recap", "Show a moderator's recent cases (/modlogs list recap)"),
    ("modlogs_edit", "Edit a moderation case (/modlogs list edit)"),
    ("modlogs_actions", "List a moderator's actions (/modlogs list actions)"),
    ("modlogs_scan", "Scan the mod-log channel for missing cases (/modlogs list scan)"),
    # Introduction tracking (Introduction.py).
    ("intro_set_channel", "Set the introductions channel (/intro set_channel)"),
    ("intro_set_role", "Set the role given after an introduction (/intro set_role)"),
    ("intro_settings", "Show introduction settings (/intro settings)"),
    ("intro_toggle", "Turn introduction tracking on or off (/intro toggle)"),
    ("intro_scan", "Scan members for missing introductions (/intro scan)"),
    ("intro_check", "Check one member's introduction (/intro check)"),
    ("intro_check_ctx", "Check Introduction (right-click a member)"),
    # WatchList (WatchList.py).
    ("watch_add", "Add a user to the watch list (/watch add)"),
    ("watch_remove", "Remove a user from the watch list (/watch remove)"),
    ("watch_add_id", "Add a user to the watch list by ID (/watch add_id)"),
    ("watch_remove_id", "Remove a user from the watch list by ID (/watch remove_id)"),
    ("watch_list", "Show everyone on the watch list (/watch list)"),
    ("watch_status", "Show the watch-list system status (/watch status)"),
    ("watch_info", "Show information about a watched user (/watch info)"),
    ("watch_set_channel", "Set the watch-list log channel (/watch set_channel)"),
    ("watch_clear", "Remove everyone from the watch list (/watch clear)"),
    # Appeals (Appeals.py).
    ("appeal_config", "Set the appeals channel / staff role (/appeal config)"),
    ("appeal_list", "List appeals (/appeal list)"),
    ("appeal_review", "Review one appeal (/appeal review)"),
    ("modnotes_search", "Keyword search across mod notes, warns, and cases (/modnotes search)"),
    # QOTD (QOTD.py, group /qotd).
    ("qotd_post", "Post today's question right now (/qotd post)"),
    ("qotd_skip", "Replace today's question with a fresh one (/qotd skip)"),
    ("qotd_config", "Set the QOTD channel, time, timezone, or on/off (/qotd config)"),
    ("qotd_pending", "List submitted questions waiting for approval (/qotd pending)"),
    ("qotd_approve", "Approve a submitted question (/qotd approve)"),
    ("qotd_reject", "Reject a submitted question (/qotd reject)"),
    ("qotd_remove", "Remove a question from the rotation (/qotd remove)"),
    # Debug (DebugCog.py, group /debug).
    ("debug_on", "Enable debug logging (/debug on)"),
    ("debug_off", "Disable debug logging (/debug off)"),
    ("debug_status", "Show debug status (/debug status)"),
    ("debug_test", "Print a test debug line to the console (/debug test)"),
    # Auto-threads (AutoThreads.py). Manage Channels by default.
    ("auto_thread_toggle", "Toggle auto-threads for the current channel (/auto_thread toggle)"),
    ("auto_thread_set_channel", "Designate a channel for auto-threads (/auto_thread toggle set_channel)"),
    ("auto_thread_remove_channel", "Stop auto-threading a channel (/auto_thread toggle remove_channel)"),
    ("auto_thread_status", "List auto-thread channels (/auto_thread toggle status)"),
    # Logger (cogs/Logger/commands.py). Administrator by default.
    ("logs_setup", "Create log channels and configure the logger (/logs setup)"),
    ("logs_change_channel", "Point one log category at a different channel (/logs change_channel)"),
    ("log_toggle_message", "Toggle message event logging (/log_toggle message)"),
    ("log_toggle_member", "Toggle member event logging (/log_toggle member)"),
    ("log_toggle_voice", "Toggle voice event logging (/log_toggle voice)"),
    ("log_toggle_server", "Toggle server event logging (/log_toggle server)"),
    ("log_toggle_moderation", "Toggle moderation event logging (/log_toggle moderation)"),
]

GRANTABLE_NAMES = [name for name, _ in GRANTABLE_COMMANDS]


def is_grantable(command):
    """True when a command/action name can have custom rules."""
    return command in GRANTABLE_NAMES


# Custom action names (website permissions page, 2026-11-16): a
# command or web key typed in by hand because it is not in the
# picker. Discord slash-command names are 1-32 lowercase letters,
# digits, underscores, or hyphens; web keys are "web:" + lowercase
# letters, digits, or underscores. Anything else is rejected (no
# spaces, slashes, dots, quotes, or uppercase -- those are never a
# real command/key name and would only be a typo or an injection
# attempt).
_CUSTOM_ACTION_RE = re.compile(
    r"^(?:web:[a-z0-9_]+|[a-z0-9_-]{1,32})$"
)


def is_valid_custom_action_name(name):
    """True when ``name`` is a well-formed command or web: key that
    may be typed in by hand on the permissions page."""
    return isinstance(name, str) and bool(_CUSTOM_ACTION_RE.match(name))


# Categories for the /perm bulk multi-select builder. Each category
# holds at most 25 commands (Discord's select limit), so the builder
# can offer every grantable command without hitting the cap.
GRANTABLE_CATEGORIES = [
    ("Moderation & roles", [
        "ban", "kick", "timeout", "warn", "clear_user", "banlog_log",
        "userinfo", "add_user_role", "remove_user_role", "rename_bot",
        "rename_user", "reset_user_name", "timeout_board",
    ]),
    ("GitHub log", [
        "banlog_set_channel", "banlog_approve", "banlog_update",
        "banlog_collect", "banlog_delete", "banlog_backfill_cases",
    ]),
    ("Level & XP", [
        "add_xp", "resetxp", "cleardata", "set_xp_rate", "set_cooldown",
        "set_level_channel", "set_level_role", "remove_level_role",
        "set_levelup_message", "toggle_no_xp",
        "toggle_levels", "no_xp_bulk",
        "xp_event", "xp_event_end",
        "level_settings", "set_spam_channel",
    ]),
    ("Badges", [
        "badge_create", "badge_award", "badge_remove", "badge_delete",
        "badge_list",
    ]),
    ("Automod", ["automod_status", "automod_toggle", "automod_config"]),
    ("Lockdown", [
        "lockdown_lock", "lockdown_unlock", "lockdown_lockall",
        "lockdown_unlockall", "lockdown_slowmode", "lockdown_status",
    ]),
    ("Backup", ["backup_now", "backup_status"]),
    ("Tickets", [
        "ticket_panel", "ticket_config", "ticket_show", "ticket_list",
    ]),
    ("Modlogs", [
        "modlogs_list", "modlogs_recap", "modlogs_edit", "modlogs_actions",
        "modlogs_scan",
    ]),
    ("Intro tracking", [
        "intro_set_channel", "intro_set_role", "intro_settings",
        "intro_toggle", "intro_scan", "intro_check", "intro_check_ctx",
    ]),
    ("WatchList", [
        "watch_add", "watch_remove", "watch_add_id", "watch_remove_id",
        "watch_list", "watch_status", "watch_info", "watch_set_channel",
        "watch_clear",
    ]),
    ("Appeals", [
        "appeal_config", "appeal_list", "appeal_review",
        "modnotes_search",
    ]),
    ("QOTD", [
        "qotd_post", "qotd_skip", "qotd_config", "qotd_pending",
        "qotd_approve", "qotd_reject", "qotd_remove",
    ]),
    ("Debug", ["debug_on", "debug_off", "debug_status", "debug_test"]),
    ("Server overview", ["bot_settings"]),
    ("AutoThreads", [
        "auto_thread_toggle", "auto_thread_set_channel",
        "auto_thread_remove_channel", "auto_thread_status",
    ]),
    ("Logger", [
        "logs_setup", "logs_change_channel",
        "log_toggle_message", "log_toggle_member", "log_toggle_voice",
        "log_toggle_server", "log_toggle_moderation",
    ]),
]


async def custom_perm_decision(guild_id, member, command):
    """Return True/False when a custom rule decides, None when the
    command has no custom rules at all (so the caller falls back to
    the command's normal Discord permission check)."""
    grants = await get_command_permissions(str(guild_id), command)
    if not grants:
        return None
    user_id = str(member.id)
    role_ids = {str(r.id) for r in (getattr(member, "roles", None) or [])}
    # 1. User-level deny wins over everything (except server admin,
    #    which the caller checks first).
    for grant in grants:
        if (
            grant.get("target_type") == "user"
            and str(grant.get("target_id")) == user_id
            and not grant.get("allowed")
        ):
            return False
    # 2. User-level allow (the training override).
    for grant in grants:
        if (
            grant.get("target_type") == "user"
            and str(grant.get("target_id")) == user_id
            and grant.get("allowed")
        ):
            return True
    # 3. Role-level deny on any of the user's roles.
    for grant in grants:
        if (
            grant.get("target_type") == "role"
            and str(grant.get("target_id")) in role_ids
            and not grant.get("allowed")
        ):
            return False
    # 4. Role-level allow on any of the user's roles.
    for grant in grants:
        if (
            grant.get("target_type") == "role"
            and str(grant.get("target_id")) in role_ids
            and grant.get("allowed")
        ):
            return True
    # Custom rules exist but nothing matches this user -> deny
    # (the custom rules replace the Discord check).
    return False


async def has_command_permission(guild, member, command, default_check):
    """Full check for one action. ``default_check`` is a callable that
    takes the member and returns whether the command's normal Discord
    permission check passes (used only when the command has no custom
    rules). Server admins always pass."""
    if guild is None or member is None:
        return False
    perms = getattr(member, "guild_permissions", None)
    if perms is not None and getattr(perms, "administrator", False):
        return True
    decision = await custom_perm_decision(guild.id, member, command)
    if decision is not None:
        return decision
    return bool(default_check(member))


def _default_manage_or_admin(member):
    """The panel / timeout default: Manage Server or Administrator."""
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(perms.manage_guild or perms.administrator)


def _default_admin_only(member):
    """The @admin_required default: Administrator only."""
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(perms.administrator)


def _default_manage_messages_or_admin(member):
    """The @Manage_messages_required / is_mod default: Manage Messages
    or Administrator."""
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(perms.manage_messages or perms.administrator)


def _default_manage_channels_or_admin(member):
    """The @Manage_channels_required default: Manage Channels or
    Administrator."""
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(perms.manage_channels or perms.administrator)


def _default_moderator_tier(member):
    """The website's old moderator-tier dashboard gate: Kick, Ban,
    Manage Messages, or Timeout Members (or Administrator). Used as
    the no-custom-rules default for ``web:view_dashboard`` so the
    dashboard keeps its old behaviour until an admin grants it
    explicitly with a custom rule."""
    perms = getattr(member, "guild_permissions", None)
    if perms is None:
        return False
    return bool(
        perms.kick_members
        or perms.ban_members
        or perms.manage_messages
        or perms.moderate_members
        or perms.administrator
    )


# Web permission system (built 2026-11-15; see bridge_api.py
# /bridge/guilds/{gid}/members/{uid}/web_access). When a website
# action has NO custom rules, has_command_permission falls back to
# the default below -- the same default the Discord command itself
# uses, taken from the check_slash_permission / check_interaction
# call sites (and cogs/Help_Info_Doc.py _HELP_DEFAULT_CHECKS, which
# was generated from those same call sites). Anything not listed
# here falls back to _default_manage_or_admin.
#
# One documented approximation: appeal_list / appeal_review default
# on Discord to is_appeal_staff(member, cfg) -- the configured staff
# role, or Manage Messages when no staff role is set. That check
# needs an async config load, so the sync fallback here is the
# no-staff-role branch: Manage Messages or Administrator.
_WEB_DISCORD_DEFAULTS = {
    # Administrator only.
    "add_user_role": _default_admin_only,
    "add_xp": _default_admin_only,
    "bot_settings": _default_admin_only,
    "cleardata": _default_admin_only,
    "clear_user": _default_admin_only,
    "level_settings": _default_admin_only,
    "logs_change_channel": _default_admin_only,
    "logs_setup": _default_admin_only,
    "log_toggle_member": _default_admin_only,
    "log_toggle_message": _default_admin_only,
    "log_toggle_moderation": _default_admin_only,
    "log_toggle_server": _default_admin_only,
    "log_toggle_voice": _default_admin_only,
    "no_xp_bulk": _default_admin_only,
    "remove_level_role": _default_admin_only,
    "remove_user_role": _default_admin_only,
    "rename_bot": _default_admin_only,
    "rename_user": _default_admin_only,
    "reset_user_name": _default_admin_only,
    "resetxp": _default_admin_only,
    "set_cooldown": _default_admin_only,
    "set_level_channel": _default_admin_only,
    "set_level_role": _default_admin_only,
    "set_levelup_message": _default_admin_only,
    "set_spam_channel": _default_admin_only,
    "set_xp_rate": _default_admin_only,
    "toggle_levels": _default_admin_only,
    "toggle_no_xp": _default_admin_only,
    "userinfo": _default_admin_only,
    "xp_event": _default_admin_only,
    "xp_event_end": _default_admin_only,
    # Manage Server or Administrator.
    "appeal_config": _default_manage_or_admin,
    "backup_now": _default_manage_or_admin,
    "badge_delete": _default_manage_or_admin,
    "ban": _default_manage_or_admin,
    "banlog_approve": _default_manage_or_admin,
    "banlog_backfill_cases": _default_manage_or_admin,
    "banlog_collect": _default_manage_or_admin,
    "banlog_delete": _default_manage_or_admin,
    "banlog_log": _default_manage_or_admin,
    "banlog_set_channel": _default_manage_or_admin,
    "banlog_update": _default_manage_or_admin,
    "debug_off": _default_manage_or_admin,
    "debug_on": _default_manage_or_admin,
    "debug_status": _default_manage_or_admin,
    "debug_test": _default_manage_or_admin,
    "intro_set_channel": _default_manage_or_admin,
    "intro_set_role": _default_manage_or_admin,
    "intro_settings": _default_manage_or_admin,
    "intro_toggle": _default_manage_or_admin,
    "kick": _default_manage_or_admin,
    "lockdown_lockall": _default_manage_or_admin,
    "lockdown_unlockall": _default_manage_or_admin,
    "modlogs_actions": _default_manage_or_admin,
    "modlogs_edit": _default_manage_or_admin,
    "modlogs_list": _default_manage_or_admin,
    "modlogs_recap": _default_manage_or_admin,
    "modlogs_scan": _default_manage_or_admin,
    "modnotes_search": _default_manage_or_admin,
    "timeout": _default_manage_or_admin,
    "timeout_board": _default_manage_or_admin,
    "warn": _default_manage_or_admin,
    "watch_add": _default_manage_or_admin,
    "watch_add_id": _default_manage_or_admin,
    "watch_clear": _default_manage_or_admin,
    "watch_info": _default_manage_or_admin,
    "watch_list": _default_manage_or_admin,
    "watch_remove": _default_manage_or_admin,
    "watch_remove_id": _default_manage_or_admin,
    "watch_set_channel": _default_manage_or_admin,
    "watch_status": _default_manage_or_admin,
    # Manage Messages or Administrator.
    "appeal_list": _default_manage_messages_or_admin,
    "appeal_review": _default_manage_messages_or_admin,
    "automod_config": _default_manage_messages_or_admin,
    "automod_status": _default_manage_messages_or_admin,
    "automod_toggle": _default_manage_messages_or_admin,
    "backup_status": _default_manage_messages_or_admin,
    "badge_award": _default_manage_messages_or_admin,
    "badge_create": _default_manage_messages_or_admin,
    "badge_list": _default_manage_messages_or_admin,
    "badge_remove": _default_manage_messages_or_admin,
    "intro_check": _default_manage_messages_or_admin,
    "intro_check_ctx": _default_manage_messages_or_admin,
    "intro_scan": _default_manage_messages_or_admin,
    "qotd_approve": _default_manage_messages_or_admin,
    "qotd_config": _default_manage_messages_or_admin,
    "qotd_pending": _default_manage_messages_or_admin,
    "qotd_post": _default_manage_messages_or_admin,
    "qotd_reject": _default_manage_messages_or_admin,
    "qotd_remove": _default_manage_messages_or_admin,
    "qotd_skip": _default_manage_messages_or_admin,
    "ticket_config": _default_manage_messages_or_admin,
    "ticket_list": _default_manage_messages_or_admin,
    "ticket_panel": _default_manage_messages_or_admin,
    "ticket_show": _default_manage_messages_or_admin,
    # Manage Channels or Administrator.
    "auto_thread_remove_channel": _default_manage_channels_or_admin,
    "auto_thread_set_channel": _default_manage_channels_or_admin,
    "auto_thread_status": _default_manage_channels_or_admin,
    "auto_thread_toggle": _default_manage_channels_or_admin,
    "lockdown_lock": _default_manage_channels_or_admin,
    "lockdown_slowmode": _default_manage_channels_or_admin,
    "lockdown_status": _default_manage_channels_or_admin,
    "lockdown_unlock": _default_manage_channels_or_admin,
}

# Web-only actions (no Discord command). The website gate asks for
# these by name; custom rules in command_permissions can grant them
# to a role/user like any Discord command, and these defaults apply
# only when no custom rule exists for the action.
# Per-section view keys (2026-11-16). Same moderator-tier
# default as web:view_dashboard, so mods/admins see every
# section by default and a section can be granted to (or
# denied from) a role/user with a custom rule.
_WEB_ONLY_DEFAULTS = {
    "web:view_dashboard": _default_moderator_tier,
    "web:manage_permissions": _default_admin_only,
    "web:manage_logs": _default_admin_only,
    "web:view_members": _default_moderator_tier,
    "web:view_leaderboard": _default_moderator_tier,
    "web:view_channels": _default_moderator_tier,
    "web:view_roles": _default_moderator_tier,
    "web:view_logger": _default_moderator_tier,
    "web:view_activity": _default_moderator_tier,
    "web:view_voice": _default_moderator_tier,
}


def web_default_check(action, member):
    """No-custom-rules default for one website action. Returns True
    when ``member`` may do ``action`` under the Discord permission
    that action's command uses (or the web-only default above).
    Unknown ``web:*`` keys fail closed (admin only); unknown Discord
    command keys fall back to Manage Server or Administrator."""
    if action in _WEB_ONLY_DEFAULTS:
        return bool(_WEB_ONLY_DEFAULTS[action](member))
    if isinstance(action, str) and action.startswith("web:"):
        return bool(_default_admin_only(member))
    check = _WEB_DISCORD_DEFAULTS.get(action)
    if check is None:
        check = _default_manage_or_admin
    return bool(check(member))


def mod_target_blocked(guild, target_id, actor_id):
    """P2-32: refuse a moderation action aimed at yourself, the bot,
    or the server owner.

    Returns a human-readable refusal, or None when the target is fine.
    The server owner may act on themselves (they already own the
    server); everyone else is refused for self, bot, and owner targets.
    Pure id comparison on guild.me / guild.owner_id -- no Discord calls.
    """
    if target_id == actor_id and actor_id != getattr(guild, "owner_id", None):
        return "You can't use moderation actions on yourself."
    bot_id = getattr(getattr(guild, "me", None), "id", None)
    if bot_id is not None and target_id == bot_id:
        return "You can't use moderation actions on me."
    owner_id = getattr(guild, "owner_id", None)
    if owner_id is not None and target_id == owner_id and actor_id != owner_id:
        return "You can't use moderation actions on the server owner."
    return None


async def check_slash_permission(ctx, command, default_check):
    """Gate for a slash command. Sends an ephemeral denial and returns
    False when the caller may not use ``command``; returns True when
    they may. ``default_check`` is the command's normal Discord check.
    """
    guild = getattr(ctx, "guild", None)
    member = getattr(ctx, "author", None)
    if guild is None or member is None:
        await ctx.respond("Use this in a server.", ephemeral=True)
        return False
    if await has_command_permission(guild, member, command, default_check):
        return True
    await ctx.respond(
        "You don't have permission to use `%s`. Ask a server admin to "
        "grant it with /perm allow." % command,
        ephemeral=True,
    )
    return False


async def check_interaction_permission(interaction, command, default_check):
    """Gate for a button/panel interaction. Sends an ephemeral denial
    and returns False when the user may not use ``command``."""
    guild = getattr(interaction, "guild", None)
    member = getattr(interaction, "user", None)
    if guild is None or member is None:
        await interaction.response.send_message(
            "Use this in a server.", ephemeral=True
        )
        return False
    if await has_command_permission(guild, member, command, default_check):
        return True
    await interaction.response.send_message(
        "You don't have permission to use `%s`. Ask a server admin to "
        "grant it with /perm allow." % command,
        ephemeral=True,
    )
    return False

# The /perm bulk builder shows every grantable command at once, in
# multi-select dropdowns (Discord caps a select at 25 options and a
# message at 5 action rows). Each group holds at most 25. There are
# five groups now, so BulkCommandView pages them four at a time --
# a fifth select plus the Grant/Back buttons would need a sixth
# action row, which Discord rejects.
BULK_COMMAND_GROUPS = [
    ("Moderation & logs", [
        "ban", "kick", "timeout", "warn", "clear_user", "banlog_log",
        "userinfo", "add_user_role", "remove_user_role", "rename_bot",
        "rename_user", "reset_user_name", "timeout_board",
        "banlog_set_channel", "banlog_approve", "banlog_update",
        "banlog_collect", "banlog_delete", "banlog_backfill_cases",
        "automod_status", "automod_toggle", "automod_config",
    ]),
    # Split 2026-11-11: "Levels, XP & badges" sat at Discord's 25-choice
    # cap, so adding level_settings + toggle_thread_xp would have pushed
    # it to 27. It is now two groups: the level commands, and voice XP
    # + badges. The /perm bulk pagination is generic (4 groups per
    # page), so the extra group just adds a second page entry.
    ("Levels & XP", [
        "add_xp", "resetxp", "cleardata", "set_xp_rate", "set_cooldown",
        "set_level_channel", "set_level_role", "remove_level_role",
        "set_levelup_message", "toggle_no_xp",
        "toggle_levels", "no_xp_bulk",
        "xp_event", "xp_event_end",
        "level_settings", "set_spam_channel",
    ]),
    ("Badges", [
        "badge_create", "badge_award", "badge_remove", "badge_delete",
        "badge_list",
    ]),
    ("Server tools", [
        "lockdown_lock", "lockdown_unlock", "lockdown_lockall",
        "lockdown_unlockall", "lockdown_slowmode", "lockdown_status",
        "backup_now", "backup_status",
        "ticket_panel", "ticket_config", "ticket_show", "ticket_list",
        "modlogs_list", "modlogs_recap", "modlogs_edit", "modlogs_actions",
        "modlogs_scan",
        "intro_set_channel", "intro_set_role", "intro_settings",
        "intro_toggle", "intro_scan", "intro_check", "intro_check_ctx",
        "bot_settings",
    ]),
    ("Community", [
        "watch_add", "watch_remove", "watch_add_id", "watch_remove_id",
        "watch_list", "watch_status", "watch_info", "watch_set_channel",
        "watch_clear",
        "appeal_config", "appeal_list", "appeal_review",
        "modnotes_search",
        "qotd_post", "qotd_skip", "qotd_config", "qotd_pending",
        "qotd_approve", "qotd_reject", "qotd_remove",
        "debug_on", "debug_off", "debug_status", "debug_test",
    ]),
    ("Logger & AutoThreads", [
        "logs_setup", "logs_change_channel",
        "log_toggle_message", "log_toggle_member", "log_toggle_voice",
        "log_toggle_server", "log_toggle_moderation",
        "auto_thread_toggle", "auto_thread_set_channel",
        "auto_thread_remove_channel", "auto_thread_status",
    ]),
]
