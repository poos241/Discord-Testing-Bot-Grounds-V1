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
pickable in /perm_allow, /perm_remove, and /perm_list. Keep the list
at 25 or fewer -- Discord caps slash-option choices at 25.
"""

from data.DB.Storage.storage import get_command_permissions

# (action name, description shown in the setup commands)
GRANTABLE_COMMANDS = [
    ("ban", "Ban a member (panel Ban button)"),
    ("kick", "Kick a member (panel Kick button)"),
    ("timeout", "Time out a member (panel button + /timeout)"),
    ("warn", "Warn a member (panel Warn button)"),
    ("clear_user", "Clear a user's messages (/clear_user)"),
    ("banlog", "Post a ban/kick log to GitHub (/banlog)"),
    ("log_approve", "Approve a GitHub log (/log_approve)"),
    ("banlog_update", "Update a GitHub log (/banlog_update)"),
    ("banlog_collect", "Collect screenshots for a log (/banlog_collect)"),
    ("banlog_delete", "Delete a GitHub log (/banlog_delete)"),
    ("ghlog_backfill_cases", "Backfill case numbers (/ghlog_backfill_cases)"),
    ("ghlog_set_channel", "Set the evidence channel (/ghlog_set_channel)"),
    # Level / XP admin commands (Level_system.py). These are powerful --
    # cleardata wipes all level data for the server -- so only grant
    # them to roles you trust. The admin decides who gets what.
    ("add_xp", "Add XP to a user (/add_xp)"),
    ("resetxp", "Reset XP and level for a user (/resetxp)"),
    ("cleardata", "Clear all level data for this server (/cleardata)"),
    ("set_xp_rate", "Set XP gain range per message (/set_xp_rate)"),
    ("set_cooldown", "Set XP gain cooldown (/set_cooldown)"),
    ("set_level_channel", "Set level-up message channel (/set_level_channel)"),
    ("set_level_role", "Set a role reward for reaching a level (/set_level_role)"),
    ("remove_level_role", "Remove a level role reward (/remove_level_role)"),
    ("set_levelup_message", "Set a custom level-up message (/set_levelup_message)"),
    ("toggle_game_xp", "Toggle XP for Eat It or Yeet It votes (/toggle_game_xp)"),
    ("toggle_no_xp", "Toggle XP gains in a channel (/toggle_no_xp)"),
    ("no_xp_bulk", "Turn XP off/on in many channels at once (/no_xp_bulk)"),
    ("bot_settings", "Show every bot system's on/off state and config (/bot_settings)"),
    ("toggle_levels", "Turn the level system on/off (/toggle_levels)"),
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
    # Voice XP admin (VoiceXP.py, group /voicexp).
    ("voicexp_config", "Show the server's voice XP settings (/voicexp config)"),
    ("voicexp_setrate", "Set XP earned per minute of voice time (/voicexp setrate)"),
    ("voicexp_setcap", "Set the daily voice XP cap (/voicexp setcap)"),
    ("voicexp_enable", "Enable voice XP for this server (/voicexp enable)"),
    ("voicexp_disable", "Disable voice XP for this server (/voicexp disable)"),
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
    ("modlogs", "Show moderation cases (/modlogs)"),
    ("modlogs_recap", "Show a moderator's recent cases (/modlogs_recap)"),
    ("modlogs_edit", "Edit a moderation case (/modlogs_edit)"),
    ("mod_actions", "List a moderator's actions (/mod_actions)"),
    # Introduction tracking (Introduction.py).
    ("intro_set_channel", "Set the introductions channel (/intro_set_channel)"),
    ("intro_set_role", "Set the role given after an introduction (/intro_set_role)"),
    ("intro_settings", "Show introduction settings (/intro_settings)"),
    ("intro_toggle", "Turn introduction tracking on or off (/intro_toggle)"),
    ("intro_scan", "Scan members for missing introductions (/intro_scan)"),
    ("intro_check", "Check one member's introduction (/intro_check)"),
    ("intro_check_ctx", "Check Introduction (right-click a member)"),
    # WatchList (WatchList.py).
    ("watch_add", "Add a user to the watch list (/watch_add)"),
    ("watch_remove", "Remove a user from the watch list (/watch_remove)"),
    ("watch_add_id", "Add a user to the watch list by ID (/watch_add_id)"),
    ("watch_remove_id", "Remove a user from the watch list by ID (/watch_remove_id)"),
    ("watch_list", "Show everyone on the watch list (/watch_list)"),
    ("watch_status", "Show the watch-list system status (/watch_status)"),
    ("watch_info", "Show information about a watched user (/watch_info)"),
    ("watch_set_channel", "Set the watch-list log channel (/watch_set_channel)"),
    ("watch_clear", "Remove everyone from the watch list (/watch_clear)"),
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
]

GRANTABLE_NAMES = [name for name, _ in GRANTABLE_COMMANDS]


def is_grantable(command):
    """True when a command/action name can have custom rules."""
    return command in GRANTABLE_NAMES


# Categories for the /perm_bulk multi-select builder. Each category
# holds at most 25 commands (Discord's select limit), so the builder
# can offer every grantable command without hitting the cap.
GRANTABLE_CATEGORIES = [
    ("Moderation & roles", [
        "ban", "kick", "timeout", "warn", "clear_user", "banlog",
        "userinfo", "add_user_role", "remove_user_role", "rename_bot",
        "rename_user", "reset_user_name", "timeout_board",
    ]),
    ("GitHub log", [
        "ghlog_set_channel", "log_approve", "banlog_update",
        "banlog_collect", "banlog_delete", "ghlog_backfill_cases",
    ]),
    ("Level & XP", [
        "add_xp", "resetxp", "cleardata", "set_xp_rate", "set_cooldown",
        "set_level_channel", "set_level_role", "remove_level_role",
        "set_levelup_message", "toggle_game_xp", "toggle_no_xp",
        "toggle_levels", "no_xp_bulk",
        "xp_event", "xp_event_end",
    ]),
    ("Voice XP", [
        "voicexp_config", "voicexp_setrate", "voicexp_setcap",
        "voicexp_enable", "voicexp_disable",
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
        "modlogs", "modlogs_recap", "modlogs_edit", "mod_actions",
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
        "grant it with /perm_allow." % command,
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
        "grant it with /perm_allow." % command,
        ephemeral=True,
    )
    return False

# The /perm_bulk builder shows every grantable command at once, in
# four multi-select dropdowns (Discord caps a select at 25 options
# and a message at 5 action rows). Each group holds at most 25.
BULK_COMMAND_GROUPS = [
    ("Moderation & logs", [
        "ban", "kick", "timeout", "warn", "clear_user", "banlog",
        "userinfo", "add_user_role", "remove_user_role", "rename_bot",
        "rename_user", "reset_user_name", "timeout_board",
        "ghlog_set_channel", "log_approve", "banlog_update",
        "banlog_collect", "banlog_delete", "ghlog_backfill_cases",
        "automod_status", "automod_toggle", "automod_config",
    ]),
    ("Levels, XP & badges", [
        "add_xp", "resetxp", "cleardata", "set_xp_rate", "set_cooldown",
        "set_level_channel", "set_level_role", "remove_level_role",
        "set_levelup_message", "toggle_game_xp", "toggle_no_xp",
        "toggle_levels", "no_xp_bulk",
        "xp_event", "xp_event_end",
        "voicexp_config", "voicexp_setrate", "voicexp_setcap",
        "voicexp_enable", "voicexp_disable",
        "badge_create", "badge_award", "badge_remove", "badge_delete",
        "badge_list",
    ]),
    ("Server tools", [
        "lockdown_lock", "lockdown_unlock", "lockdown_lockall",
        "lockdown_unlockall", "lockdown_slowmode", "lockdown_status",
        "backup_now", "backup_status",
        "ticket_panel", "ticket_config", "ticket_show", "ticket_list",
        "modlogs", "modlogs_recap", "modlogs_edit", "mod_actions",
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
]
