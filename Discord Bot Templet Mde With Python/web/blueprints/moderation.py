"""Moderation API — the ONE moderation blueprint.

All write operations go through ``ModerationService`` (a bridge
client) via ``run_coro_threadsafe`` on the website's local loop,
because Flask runs in threads beside the bot's asyncio loop. Every
route requires login + the matching guild permission. When the bot
is unreachable the actions answer 503 (degraded), never 400.
"""

from flask import Blueprint, request, jsonify, abort
import secrets
from web.blueprints.auth import get_csrf_token

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.services.discord_state import run_coro_threadsafe
from web.services.moderation_service import ModerationService, ModerationError
from web.security.decorators import require_web_api_access


moderation_api = Blueprint(
    "moderation",
    __name__,
    url_prefix="/api/servers"
)


def _service():
    # Bridge split: no live bot object in this process. ModerationService
    # is a bridge client now (constructed with no bot arg); the 503
    # behaviour when the bot is down is unchanged.
    if not bridge.bot_is_ready():
        abort(503, "Discord bot is not connected.")
    return ModerationService()


# ============================================================
# MOD-CASE WRITE MITIGATION (cross-process last-writer-wins)
#
# mod_data.json lives in bot.db, which BOTH processes read and write
# (the bot's slash commands/panels and this website). There is no
# cross-process lock, so a bot-side save that loaded before ours can
# silently overwrite our save. Cheap mitigation, per the bridge
# contract section 8: after saving, re-read fresh and check the
# change actually landed; if it did not, re-apply it on the fresh
# load and save once more. One retry only.
#
# What remains unmitigated: two writers can still interleave on the
# SECOND save (a bot save landing between our verify and our retry
# still loses our change), and two appends of the SAME entry can both
# land if the verify read races a bot save (duplicate warn/case).
# A real fix needs a cross-process lock or a bot-owned mod-case
# endpoint; this narrows the window from "any concurrent bot write"
# to "a bot write inside our verify+retry window".
# ============================================================

def _save_mod_record(guild_id, user_id, mutate, verify):
    """Load-mutate-save a mod_data user record with one re-read retry.

    mutate(urec) applies the change; verify(urec) is True when the
    change is visible in a fresh load. Returns the fresh urec, or
    None when the mod-data helpers are unavailable or a save failed.
    """
    try:
        from cogs.admin_cog import _mod_record, _save_mod_data
    except Exception:
        return None
    try:
        data, urec = _mod_record(str(guild_id), str(user_id))
        mutate(urec)
        _save_mod_data(data)
    except Exception:
        return None
    try:
        data2, fresh = _mod_record(str(guild_id), str(user_id))
        if verify(fresh):
            return fresh
        mutate(fresh)
        _save_mod_data(data2)
        return fresh
    except Exception:
        return None


def _save_tempban(guild_id, user_id, entry):
    """Store a tempban expiry with the same re-read + one retry."""
    try:
        from cogs.admin_cog import _tempban_data, _save_mod_data
    except Exception:
        return False
    until = entry.get("until")
    try:
        data, tempbans = _tempban_data(guild_id)
        tempbans[str(user_id)] = dict(entry)
        _save_mod_data(data)
    except Exception:
        return False
    try:
        data2, fresh = _tempban_data(guild_id)
        if (fresh.get(str(user_id)) or {}).get("until") == until:
            return True
        fresh[str(user_id)] = dict(entry)
        _save_mod_data(data2)
        return True
    except Exception:
        return False


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
    # Bridge down on a moderation action is a 503 (degraded), not a
    # 400: ModerationService re-raises BridgeUnavailable as-is for
    # exactly this. Hierarchy/validation refusals stay 400.
    if isinstance(e, BridgeUnavailable):
        code = 503
    elif isinstance(e, ModerationError):
        code = 400
    else:
        code = 500
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
        label, uid, avatar_url = _moderator()
        # label is "Name (id)"; split for separate fields
        mod_name = label.rsplit(" (", 1)[0] if " (" in label else label
        ex = dict(extra or {})
        case = {
            "action": action,
            "reason": reason,
            "moderator": mod_name,
            "moderator_id": uid,
            "moderator_avatar": avatar_url,
            "evidence": ex.get("evidence"),
            "dm_sent": ex.get("dm_sent", False),
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

        def _mutate(urec):
            cases = urec.setdefault("cases", [])
            cases.append(case)
            if len(cases) > 50:
                cases[:] = cases[-50:]

        def _verify(urec):
            return case in (urec.get("cases") or [])

        _save_mod_record(guild_id, user_id, _mutate, _verify)
    except Exception:
        pass


def _guild_name(guild_id):
    """Guild display name for DM text, via the bridge. Falls back to
    'the server' when the bot is down or the guild is unknown."""
    try:
        guild = bridge.get_guild(int(guild_id))
        if guild:
            return guild.get("name") or "the server"
    except Exception:
        pass
    return "the server"


def _dm_member(guild_id, user_id, text):
    """DM via the bridge (same _dm_target helper, bot-side). False
    when DMs are closed or the bot is unreachable."""
    try:
        service = ModerationService()
        result = run_coro_threadsafe(
            service.send_dm(guild_id, user_id, text)
        ).result(timeout=20)
        if isinstance(result, dict):
            return bool(result.get("sent"))
        return bool(result)
    except Exception:
        return False


def _get_member(guild_id, user_id):
    """Return (guild_dict, member_dict) or (None, None).

    (guild, None) means the server is known but the user is not a
    member of it; (None, None) means the server is unknown or the
    bot is down. Mirrors web/blueprints/modpanel.py.
    """
    try:
        guild = bridge.get_guild(int(guild_id))
    except Exception:
        return None, None
    if guild is None:
        return None, None
    try:
        member = bridge.get_member(int(guild_id), int(user_id))
    except Exception:
        return guild, None
    return guild, member


def _bot_down_response():
    """503 when the bridge is down, else 404 (server unknown)."""
    if not bridge.bot_is_ready():
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
        }), 503
    return jsonify({
        "success": False,
        "error": "Discord server not found.",
    }), 404


def _not_in_server_response():
    """404 when the target is no longer a member of the guild."""
    return jsonify({
        "success": False,
        "error": "This member is no longer in the server.",
    }), 404


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
@require_web_api_access("timeout")
def timeout_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    # Stop here when the target is no longer in the server.
    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return _bot_down_response()
    if member is None:
        return _not_in_server_response()

    data = request.get_json(silent=True) or {}
    try:
        duration = int(data.get("duration", 600))
    except (TypeError, ValueError):
        duration = 600
    reason = data.get("reason") or "No reason provided."
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    if want_dm:
        dm_sent = _dm_member(
            guild_id, user_id,
            f"⏱️ You've been timed out in **{_guild_name(guild_id)}**\n**Reason:** {reason}",
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
@require_web_api_access("timeout")
def remove_timeout_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    # Stop here when the target is no longer in the server.
    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return _bot_down_response()
    if member is None:
        return _not_in_server_response()

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
@require_web_api_access("kick")
def kick_member(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    # Stop here when the target is no longer in the server.
    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return _bot_down_response()
    if member is None:
        return _not_in_server_response()

    data = request.get_json(silent=True) or {}
    reason = data.get("reason") or "No reason provided."
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    if want_dm:
        dm_sent = _dm_member(
            guild_id, user_id,
            f"👢 You've been kicked from **{_guild_name(guild_id)}**\n**Reason:** {reason}",
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
@require_web_api_access("ban")
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
        dm_sent = _dm_member(
            guild_id, user_id,
            f"🔨 You've been banned from **{_guild_name(guild_id)}**\n**Reason:** {reason}",
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
@require_web_api_access("ban")
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
