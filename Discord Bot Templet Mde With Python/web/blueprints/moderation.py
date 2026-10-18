"""Moderation API — the ONE moderation blueprint.

All write operations go through ``run_coro_threadsafe`` from the
discord_state shim, because Flask runs in a thread beside the bot's
asyncio loop. Every route requires login + Manage Server on the guild.
"""

from flask import Blueprint, request, jsonify, abort

from web.services.discord_state import discord_state, run_coro_threadsafe
from web.services.moderation_service import ModerationService, ModerationError
from web.security.decorators import require_guild_access, require_guild_manage


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


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/timeout"
)
@require_guild_access
@require_guild_manage
def timeout_member(guild_id, user_id):
    data = request.get_json(silent=True) or {}
    try:
        duration = int(data.get("duration", 600))
    except (TypeError, ValueError):
        duration = 600
    reason = data.get("reason")
    service = _service()
    try:
        run_coro_threadsafe(
            service.timeout(guild_id, user_id, duration, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    return _ok("timeout", guild_id, user_id,
               duration=duration, reason=reason)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/remove-timeout"
)
@require_guild_access
@require_guild_manage
def remove_timeout_member(guild_id, user_id):
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
@require_guild_access
@require_guild_manage
def kick_member(guild_id, user_id):
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    service = _service()
    try:
        run_coro_threadsafe(
            service.kick(guild_id, user_id, reason)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    return _ok("kick", guild_id, user_id)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/ban"
)
@require_guild_access
@require_guild_manage
def ban_member(guild_id, user_id):
    data = request.get_json(silent=True) or {}
    reason = data.get("reason")
    try:
        delete_days = int(data.get("delete_message_days", 0))
    except (TypeError, ValueError):
        delete_days = 0
    delete_days = max(0, min(delete_days, 7))
    service = _service()
    try:
        run_coro_threadsafe(
            service.ban(guild_id, user_id, reason, delete_days)
        ).result(timeout=20)
    except Exception as e:
        return _fail(e)
    return _ok("ban", guild_id, user_id)


@moderation_api.post(
    "/<int:guild_id>/members/<int:user_id>/unban"
)
@require_guild_access
@require_guild_manage
def unban_member(guild_id, user_id):
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
