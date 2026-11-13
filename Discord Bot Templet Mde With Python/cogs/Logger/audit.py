"""Helper for reading Discord's audit log."""
import asyncio
import time

import discord


class Audit:
    @staticmethod
    async def latest(guild, action, target_id=None, limit=5):
        """Return the most recent audit-log entry for an action.

        When target_id is given, only entries targeting that user/channel
        are considered, so the moderator/reason actually match the event.
        """
        try:
            async for entry in guild.audit_logs(limit=limit, action=action):
                if target_id is None:
                    return entry
                target = entry.target
                if target is not None and getattr(target, "id", None) == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None


# ----- moderator resolution -----
# A bot-issued ban/kick/timeout/unban is recorded in the audit log with
# the BOT as the executor (Discord records whoever called the API), so
# entry.user is the bot, not the human mod who ran the command. The
# human is in the mod-data case written right after the action, so when
# the executor is the bot (or there is no audit entry at all) we look
# the case up and use its mod_id / mod_name instead. One retry after a
# short sleep covers the race where the gateway event fires before the
# case write lands.

_CASE_MAX_AGE = 300  # seconds; a case older than this is a previous action, not this one
_CASE_RETRY_DELAY = 1.5  # seconds to wait for the case write, then look once more


def _avatar_url(user):
    try:
        return user.display_avatar.url
    except Exception:
        return None


async def _find_recent_case(guild_id, target_id, case_actions):
    """Newest mod-data case for the target whose action label matches
    ``case_actions`` and whose ts is within _CASE_MAX_AGE seconds.
    The blocking SQLite read runs in a worker thread so the gateway
    loop never stalls. Returns the case dict, or None."""
    try:
        from config import load_json
    except ImportError:
        return None
    try:
        data = await asyncio.to_thread(load_json, "mod_data.json")
    except Exception:
        return None
    if not data:
        return None
    urec = (data.get(str(guild_id)) or {}).get(str(target_id)) or {}
    cases = urec.get("cases") or []
    now = time.time()
    for case in reversed(cases):
        label = case.get("action") or ""
        if not any(label == a or label.startswith(a + " ") for a in case_actions):
            continue
        # Cases are newest-last, so the first match scanning backwards
        # is the newest one; if it is too old, older ones are older.
        if now - (case.get("ts") or 0) > _CASE_MAX_AGE:
            return None
        return case
    return None


async def _moderator_from_case(guild, bot, case, audit_reason):
    """Build the moderator dict from a mod-data case. Resolves the
    member/user object for the avatar when possible; falls back to the
    stored mod_name with no avatar when it cannot be resolved."""
    mod_id = case.get("mod_id")
    mod_name = case.get("mod_name") or "Unknown"
    reason = case.get("reason") or audit_reason
    resolved = None
    if mod_id:
        try:
            resolved = guild.get_member(int(mod_id))
        except (TypeError, ValueError):
            resolved = None
        if resolved is None and bot is not None:
            try:
                resolved = await bot.fetch_user(int(mod_id))
            except (discord.NotFound, discord.Forbidden,
                    discord.HTTPException, TypeError, ValueError):
                resolved = None
    if resolved is not None:
        return {
            "name": getattr(resolved, "name", str(resolved)),
            "display": str(resolved),
            "mention": getattr(resolved, "mention", str(resolved)),
            "avatar_url": _avatar_url(resolved),
            "reason": reason,
            "from_case": True,
        }
    return {
        "name": mod_name,
        "display": mod_name,
        "mention": f"<@{mod_id}>" if mod_id else mod_name,
        "avatar_url": None,
        "reason": reason,
        "from_case": True,
    }


async def resolve_moderator(guild, bot, action, target_id, case_actions, entry=None):
    """Resolve who performed a moderation action.

    Returns a dict with ``name`` (username, for [name] brackets and
    "Banned by X"), ``display`` (str(user)-style name, for the
    kept-as-is Moderator fields), ``mention``, ``avatar_url`` (or
    None), ``reason`` (case reason when the case was used, else the
    audit-log reason), and ``from_case``.

    ``entry`` may be an audit entry the caller already fetched (the
    kick path has one); otherwise it is looked up here. When the
    executor is the bot itself -- or there is no audit entry -- the
    newest matching mod-data case identifies the human mod.
    """
    if entry is None:
        entry = await Audit.latest(guild, action, target_id=target_id)
    bot_id = getattr(getattr(bot, "user", None), "id", None)
    executor_is_bot = (
        entry is not None
        and getattr(entry, "user", None) is not None
        and bot_id is not None
        and entry.user.id == bot_id
    )
    audit_reason = getattr(entry, "reason", None) if entry is not None else None

    if entry is None or executor_is_bot:
        case = await _find_recent_case(guild.id, target_id, case_actions)
        if case is None:
            # The gateway event can fire before the case write lands.
            await asyncio.sleep(_CASE_RETRY_DELAY)
            case = await _find_recent_case(guild.id, target_id, case_actions)
        if case is not None:
            return await _moderator_from_case(guild, bot, case, audit_reason)

    if entry is not None and getattr(entry, "user", None) is not None:
        user = entry.user
        return {
            "name": getattr(user, "name", str(user)),
            "display": str(user),
            "mention": getattr(user, "mention", str(user)),
            "avatar_url": _avatar_url(user),
            "reason": audit_reason,
            "from_case": False,
        }

    return {
        "name": "Unknown",
        "display": "Unknown",
        "mention": "Unknown",
        "avatar_url": None,
        "reason": audit_reason,
        "from_case": False,
    }
