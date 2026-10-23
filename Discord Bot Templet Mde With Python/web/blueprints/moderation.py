"""Moderation API — the ONE moderation blueprint.

All write operations go through ``run_coro_threadsafe`` from the
discord_state shim, because Flask runs in a thread beside the bot's
asyncio loop. Every route requires login + Manage Server on the guild.
"""

from flask import Blueprint, request, jsonify, abort
import secrets
from web.blueprints.auth import get_csrf_token

from web.services.discord_state import discord_state, run_coro_threadsafe
from web.services.moderation_service import ModerationService, ModerationError
from web.security.decorators import (
    require_guild_manage,
    require_guild_moderator,
)


moderation_api = Blueprint(
    "moderation",
    __name__,
    url_prefix="/api/servers"
)


def _service():
    bot = discord_state.get_bot()
    if bot is None or not discord_state.ready:
        abort(503, "Discord bot is not connected.")
    return ModerationService(bot)


def _ok(action, guild_id, user_id, **extra):
    payload = {
        "success": True,
        "action": action,
        "guild_id": str(guild_id),
        "user_id": str(user_id),
    }
    payload.update(extra)
    return jsonify(payload)


def _fail(e):
    code = 400 if isinstance(e, ModerationError) else 500
    return jsonify({"success": False, "error": str(e)}), code


def _moderator():
    from flask import session
    user = session.get("user") or {}
    name = (
        user.get("global_name")
        or user.get("username")
        or (f"User {user.get('id')}" if user.get("id") else None)
        or "Web dashboard"
    )
    uid = str(user.get("id") or "")
    avatar_hash = user.get("avatar")
    avatar_url = (
        f"https://cdn.discordapp.com/avatars/{uid}/{avatar_hash}.png"
        if uid and avatar_hash else None
    )
    label = f"{name} ({uid})" if uid else name
    return label, uid, avatar_url


def _record_web_case(guild_id, user_id, action, reason, extra=None):
    import datetime
    try:
        from cogs.admin_cog import _mod_record, _save_mod_data
        label, uid, avatar_url = _moderator()
        # label is "Name (id)"; split for separate fields
        mod_name = label.rsplit(" (", 1)[0] if " (" in label else label
        ex = dict(extra or {})
        mod_data, urec = _mod_record(str(guild_id), str(user_id))
        cases = urec.setdefault("cases", [])
        cases.append({
            "action": action,
            "reason": reason,
            "moderator": mod_name,
            "moderator_id": uid,
            "moderator_avatar": avatar_url,
            "evidence": ex.get("evidence"),
            "dm_sent": ex.get("dm_sent", False),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        if len(cases) > 50:
            cases[:] = cases[-50:]
        _save_mod_data(mod_data)
    except Exception:
        pass


def _dm_member(guild_id, user_id, text):
    try:
        from cogs.admin_cog import _dm_target
        bot = discord_state.bot
        if not bot:
            return False
        guild = bot.get_guild(int(guild_id))
        if not guild:
            return False
        member = guild.get_member(int(user_id))
        if not member:
            return False
        return bool(
            run_coro_threadsafe(_dm_target(member, text)).result(timeout=15)
        )
    except Exception:
        return False


def _check_csrf():
    """Validate the CSRF token on state-changing requests."""
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 403
    return None


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/timeout"
)
@require_guild_moderator
def timeout_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    try:
        duration = int(data.get("duration", 600))
    except (TypeError, ValueError):
        duration = 600
    reason = data.get("reason") or "No reason provided."
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    if want_dm:
        bot = discord_state.bot
        guild = bot.get_guild(int(guild_id)) if bot else None
        gname = guild.name if guild else "the server"
        dm_sent = _dm_member(
            guild_id, user_id,
            f"⏱️ You've been timed out in **{gname}**\n**Reason:** {reason}",
        )
    else:
        dm_sent = False

    service = _service()
    try:
        run_coro_threadsafe(
            service.timeout(guild_id, user_id, duration, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    _record_web_case(
        guild_id, user_id, "timeout", reason,
        extra={"duration": duration, "evidence": evidence, "dm_sent": dm_sent},
    )
    return _ok("timeout", guild_id, user_id,
               duration=duration, reason=reason, dm_sent=dm_sent)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/remove-timeout"
)
@require_guild_moderator
def remove_timeout_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    service = _service()
    try:
        run_coro_threadsafe(
            service.remove_timeout(guild_id, user_id, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    return _ok("remove_timeout", guild_id, user_id)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/kick"
)
@require_guild_moderator
def kick_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    reason = data.get("reason") or "No reason provided."
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    if want_dm:
        bot = discord_state.bot
        guild = bot.get_guild(int(guild_id)) if bot else None
        gname = guild.name if guild else "the server"
        dm_sent = _dm_member(
            guild_id, user_id,
            f"👢 You've been kicked from **{gname}**\n**Reason:** {reason}",
        )
    else:
        dm_sent = False

    service = _service()
    try:
        run_coro_threadsafe(
            service.kick(guild_id, user_id, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    _record_web_case(
        guild_id, user_id, "kick", reason,
        extra={"evidence": evidence, "dm_sent": dm_sent},
    )
    return _ok("kick", guild_id, user_id, dm_sent=dm_sent)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/ban"
)
@require_guild_moderator
def ban_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    reason = data.get("reason") or "No reason provided."
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None
    try:
        delete_days = int(data.get("delete_message_days", 0))
    except (TypeError, ValueError):
        delete_days = 0
    delete_days = max(0, min(delete_days, 7))

    if want_dm:
        bot = discord_state.bot
        guild = bot.get_guild(int(guild_id)) if bot else None
        gname = guild.name if guild else "the server"
        dm_sent = _dm_member(
            guild_id, user_id,
            f"🔨 You've been banned from **{gname}**\n**Reason:** {reason}",
        )
    else:
        dm_sent = False

    service = _service()
    try:
        run_coro_threadsafe(
            service.ban(guild_id, user_id, reason, delete_days)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    _record_web_case(
        guild_id, user_id, "ban", reason,
        extra={"evidence": evidence, "dm_sent": dm_sent},
    )
    return _ok("ban", guild_id, user_id, dm_sent=dm_sent)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/unban"
)
@require_guild_moderator
def unban_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    service = _service()
    try:
        run_coro_threadsafe(
            service.unban(guild_id, user_id, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    return _ok("unban", guild_id, user_id)
