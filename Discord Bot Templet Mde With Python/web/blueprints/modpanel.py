# web/blueprints/modpanel.py
#
# Web version of the /userinfo mini-admin panel.
# Provides member moderation data and actions via the web dashboard.
#
# Data layer: imports module-level helpers from cogs.admin_cog
# (they operate directly on data/mod_data.json).

from flask import Blueprint, request, jsonify

import secrets

from flask import session

from web.services.discord_state import discord_state, run_coro_threadsafe
from web.security.decorators import (
    require_guild_moderator,
)
from web.blueprints.auth import get_csrf_token


def _record_case_direct(guild_id, user_id, action, reason, evidence=None, dm_sent=False):
    """Record a case directly to mod_data.json with full moderator attribution."""
    import datetime
    try:
        _mod_record, _, _save_mod_data = _mod_helpers()
        if not _mod_record:
            return
        mod_name, mod_id, mod_avatar = _moderator()
        mod_data, urec = _mod_record(str(guild_id), str(user_id))
        cases = urec.setdefault("cases", [])
        cases.append({
            "action": action,
            "reason": reason,
            "moderator": mod_name,
            "moderator_id": mod_id,
            "moderator_avatar": mod_avatar,
            "evidence": evidence,
            "dm_sent": dm_sent,
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        })
        # Keep last 50
        if len(cases) > 50:
            cases[:] = cases[-50:]
        _save_mod_data(mod_data)
    except Exception:
        pass


def _moderator():
    """Return (name, id, avatar_url) of the logged-in Discord user."""
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
    return name, uid, avatar_url


def _try_dm(member, text):
    """Try to DM the member. Returns True on success."""
    try:
        from cogs.admin_cog import _dm_target
        return bool(
            run_coro_threadsafe(_dm_target(member, text)).result(timeout=15)
        )
    except Exception:
        return False


modpanel_api = Blueprint(
    "modpanel",
    __name__,
    url_prefix="/api",
)


def _check_csrf():
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 403
    return None


def _get_member(guild_id, user_id):
    """Return (guild, member_or_user) or (None, None)."""
    bot = discord_state.bot
    if bot is None or not discord_state.ready:
        return None, None
    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return None, None
    member = guild.get_member(int(user_id))
    if member is None:
        try:
            member = run_coro_threadsafe(
                guild.fetch_member(int(user_id))
            ).result(timeout=15)
        except Exception:
            member = None
    return guild, member


def _mod_helpers():
    """Import mod-data helpers from the bot's AdminCog module."""
    try:
        from cogs.admin_cog import _mod_record, _record_case, _save_mod_data
        return _mod_record, _record_case, _save_mod_data
    except Exception as e:
        return None, None, None


def _watch_cog():
    bot = discord_state.bot
    if bot is None:
        return None
    try:
        return bot.get_cog("WatchList")
    except Exception:
        return None


def _xp_for(guild_id, user_id):
    """Return (xp, level) from the level system, or (0, 1)."""
    try:
        from data.DB.Storage.storage import get_levels
        db = run_coro_threadsafe(
            get_levels(str(guild_id))
        ).result(timeout=10)
        udata = db.get(str(user_id))
        if udata:
            return udata.get("xp", 0) or 0, udata.get("level", 1) or 1
    except Exception:
        pass
    return 0, 1


# ============================================================
# GET MOD PANEL DATA
#
# GET /api/servers/<guild_id>/members/<user_id>/modpanel
# ============================================================

@modpanel_api.get(
    "/servers/<int:guild_id>/members/<int:user_id>/modpanel"
)
@require_guild_moderator
def get_modpanel(guild_id, user_id):
    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found or bot not ready.",
        }), 503

    _mod_record, _, _ = _mod_helpers()
    warns, notes, cases = [], [], []
    if _mod_record:
        try:
            _, urec = _mod_record(guild_id, user_id)
            warns = urec.get("warns", [])
            notes = urec.get("notes", [])
            cases = urec.get("cases", [])
        except Exception:
            pass

    # Watch status
    watched = False
    watch_info = None
    wc = _watch_cog()
    if wc:
        try:
            if hasattr(wc, "_guild_data"):
                gdata = wc._guild_data(guild_id)
                rec = gdata.get("users", {}).get(str(user_id))
                if rec:
                    watched = True
                    watch_info = rec
            elif hasattr(wc, "_is_watched"):
                watched = bool(wc._is_watched(str(guild_id), str(user_id)))
        except Exception:
            pass

    xp, level = _xp_for(guild_id, user_id)

    # Member info
    minfo = {"id": str(user_id), "is_member": member is not None}
    if member:
        try:
            minfo.update({
                "name": member.name,
                "display_name": member.display_name,
                "discriminator": getattr(member, "discriminator", "0"),
                "avatar": str(member.display_avatar.url) if member.display_avatar else None,
                "bot": bool(getattr(member, "bot", False)),
                "joined_at": member.joined_at.isoformat() if getattr(member, "joined_at", None) else None,
                "created_at": member.created_at.isoformat() if getattr(member, "created_at", None) else None,
                "roles": [
                    {"id": str(r.id), "name": r.name, "color": r.color.value}
                    for r in getattr(member, "roles", [])
                    if r.name != "@everyone"
                ],
                "timed_out": member.is_timed_out() if hasattr(member, "is_timed_out") else False,
            })
        except Exception:
            pass

    from web.services.permissions import get_access_level

    return jsonify({
        "success": True,
        "member": minfo,
        "warns": warns,
        "notes": notes,
        "cases": cases[-20:][::-1] if cases else [],  # newest first, last 20
        "watched": watched,
        "watch_info": watch_info,
        "xp": xp,
        "level": level,
        # Lets the frontend hide mod-action buttons from non-moderators.
        "access_level": get_access_level(guild_id) or "none",
    })


# ============================================================
# WARN
#
# POST /api/servers/<guild_id>/members/<user_id>/warn
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/warn"
)
@require_guild_moderator
def modpanel_warn(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "No reason provided.").strip()
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    mod_name, mod_id, mod_avatar = _moderator()
    mod_label = f"{mod_name} ({mod_id})" if mod_id else mod_name

    _mod_record, _record_case, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({
            "success": False,
            "error": "Mod data helpers unavailable.",
        }), 500

    # DM first (before any action that might remove them)
    dm_sent = False
    if want_dm:
        guild, member = _get_member(guild_id, user_id)
        if member:
            dm_sent = _try_dm(
                member,
                f"⚠️ You've been warned in **{guild.name}**\n**Reason:** {reason}",
            )

    mod_data, urec = _mod_record(guild_id, user_id)
    warns = urec.setdefault("warns", [])
    warns.append({
        "reason": reason,
        "moderator": mod_label,
        "moderator_id": mod_id,
        "moderator_avatar": mod_avatar,
        "evidence": evidence,
        "dm_sent": dm_sent,
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })
    _save_mod_data(mod_data)
    _record_case_direct(guild_id, user_id, "warn", reason,
                        evidence=evidence, dm_sent=dm_sent)

    return jsonify({"success": True, "warn_count": len(warns), "dm_sent": dm_sent})


# ============================================================
# NOTES
#
# POST /api/servers/<guild_id>/members/<user_id>/notes
# DELETE /api/servers/<guild_id>/members/<user_id>/notes/<int:index>
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/notes"
)
@require_guild_moderator
def modpanel_add_note(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"success": False, "error": "Note text required."}), 400

    _mod_record, _record_case, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500

    mod_data, urec = _mod_record(guild_id, user_id)
    notes = urec.setdefault("notes", [])
    notes.append({
        "text": text,
        "moderator": "Web dashboard",
        "timestamp": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    })
    _save_mod_data(mod_data)

    return jsonify({"success": True, "note_count": len(notes)})


@modpanel_api.delete(
    "/servers/<int:guild_id>/members/<int:user_id>/notes/<int:index>"
)
@require_guild_moderator
def modpanel_delete_note(guild_id, user_id, index):
    denied = _check_csrf()
    if denied:
        return denied

    _mod_record, _, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500

    mod_data, urec = _mod_record(guild_id, user_id)
    notes = urec.get("notes", [])
    if index < 0 or index >= len(notes):
        return jsonify({"success": False, "error": "Note not found."}), 404
    notes.pop(index)
    _save_mod_data(mod_data)

    return jsonify({"success": True, "note_count": len(notes)})


# ============================================================
# WATCH / UNWATCH
#
# POST /api/servers/<guild_id>/members/<user_id>/watch
# DELETE /api/servers/<guild_id>/members/<user_id>/watch
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/watch"
)
@require_guild_moderator
def modpanel_watch(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    wc = _watch_cog()
    if wc is None:
        return jsonify({"success": False, "error": "WatchList cog not loaded."}), 503

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "Watched via web dashboard.").strip()

    mod_name, mod_id, _ = _moderator()
    mod_label = f"{mod_name} ({mod_id})" if mod_id else mod_name

    try:
        if hasattr(wc, "watch_add"):
            result = wc.watch_add(str(guild_id), str(user_id))
            if hasattr(result, "__await__"):
                run_coro_threadsafe(result).result(timeout=15)
        # Set reason/moderator directly on the watch entry
        try:
            users = wc._guild_data(str(guild_id)).get("users", {})
            entry = users.get(str(user_id))
            if isinstance(entry, dict):
                entry["reason"] = reason
                entry["added_by"] = mod_label
        except Exception:
            pass
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    _record_case_direct(guild_id, user_id, "watch", reason)

    return jsonify({"success": True, "watched": True})


@modpanel_api.delete(
    "/servers/<int:guild_id>/members/<int:user_id>/watch"
)
@require_guild_moderator
def modpanel_unwatch(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    wc = _watch_cog()
    if wc is None:
        return jsonify({"success": False, "error": "WatchList cog not loaded."}), 503

    try:
        if hasattr(wc, "watch_remove"):
            result = wc.watch_remove(str(guild_id), str(user_id))
            if hasattr(result, "__await__"):
                run_coro_threadsafe(result).result(timeout=15)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    _record_case_direct(guild_id, user_id, "unwatch", "Watch removed via web dashboard.")

    return jsonify({"success": True, "watched": False})


# ============================================================
# XP
#
# POST /api/servers/<guild_id>/members/<user_id>/xp  {amount}
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/xp"
)
@require_guild_moderator
def modpanel_xp(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    try:
        amount = int(data.get("amount", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "Invalid amount."}), 400
    if amount == 0:
        return jsonify({"success": False, "error": "Amount cannot be zero."}), 400

    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return jsonify({"success": False, "error": "Discord server not found."}), 404
    display = member.display_name if member else str(user_id)

    try:
        from cogs.Level_system import award_xp
        run_coro_threadsafe(
            award_xp(guild, int(user_id), display, amount, apply_event=False)
        ).result(timeout=15)
    except Exception as e:
        return jsonify({"success": False, "error": f"XP update failed: {e}"}), 500

    _, _record_case, _ = _mod_helpers()
    action = "add_xp" if amount > 0 else "remove_xp"
    _record_case_direct(guild_id, user_id, action, f"{amount} XP")

    xp, level = _xp_for(guild_id, user_id)
    return jsonify({"success": True, "xp": xp, "level": level})


# ============================================================
# RENAME
#
# POST /api/servers/<guild_id>/members/<user_id>/rename  {nickname}
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/rename"
)
@require_guild_moderator
def modpanel_rename(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None or member is None:
        return jsonify({"success": False, "error": "Member not found."}), 404

    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip() or None  # None resets

    try:
        run_coro_threadsafe(member.edit(nick=nickname)).result(timeout=15)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    _, _record_case, _ = _mod_helpers()
    _record_case_direct(
        guild_id, user_id, "rename",
        f"Nickname set to '{nickname}'" if nickname else "Nickname reset",
    )

    return jsonify({"success": True})


# ============================================================
# STRIP ROLES
#
# POST /api/servers/<guild_id>/members/<user_id>/strip-roles
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/strip-roles"
)
@require_guild_moderator
def modpanel_strip_roles(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None or member is None:
        return jsonify({"success": False, "error": "Member not found."}), 404

    removed = []
    try:
        roles_to_remove = [r for r in member.roles if r.name != "@everyone"]
        removed = [r.name for r in roles_to_remove]
        if roles_to_remove:
            run_coro_threadsafe(
                member.remove_roles(*roles_to_remove, reason="Strip roles via web dashboard")
            ).result(timeout=20)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    _, _record_case, _ = _mod_helpers()
    _record_case_direct(
        guild_id, user_id, "strip_roles",
        f"Removed {len(removed)} roles: {', '.join(removed[:10])}",
    )

    return jsonify({"success": True, "removed": removed})


# ============================================================
# CLEAR MESSAGES
#
# POST /api/servers/<guild_id>/members/<user_id>/clear  {amount}
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/clear"
)
@require_guild_moderator
def modpanel_clear(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return jsonify({"success": False, "error": "Discord server not found."}), 404

    data = request.get_json(silent=True) or {}
    try:
        amount = max(1, min(int(data.get("amount", 10)), 100))
    except (TypeError, ValueError):
        amount = 10

    cleared = 0
    target_id = int(user_id)
    for channel in guild.text_channels:
        if cleared >= amount:
            break
        try:
            perms = channel.permissions_for(guild.me)
            if not (perms.read_messages and perms.manage_messages):
                continue
        except Exception:
            continue
        try:
            deleted = run_coro_threadsafe(
                channel.purge(
                    limit=200,
                    check=lambda m: m.author.id == target_id,
                )
            ).result(timeout=30)
            cleared += len(deleted)
        except Exception:
            continue

    _, _record_case, _ = _mod_helpers()
    _record_case_direct(
        guild_id, user_id, "clear",
        f"Cleared ~{cleared} messages via web dashboard.",
    )

    return jsonify({"success": True, "cleared": cleared})


# ============================================================
# TEMPBAN
#
# POST /api/servers/<guild_id>/members/<user_id>/tempban  {duration, reason}
# Duration like "7d", "12h", "30m". Stored in mod_data.json;
# AdminCog's 1-minute sweep auto-unbans when it expires.
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/tempban"
)
@require_guild_moderator
def modpanel_tempban(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return jsonify({"success": False, "error": "Discord server not found."}), 404

    data = request.get_json(silent=True) or {}
    duration_str = (data.get("duration") or "").strip()
    reason = (data.get("reason") or "No reason provided.").strip()
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    mod_name, mod_id, mod_avatar = _moderator()
    mod_label = f"{mod_name} ({mod_id})" if mod_id else mod_name

    # Parse duration
    import re as _re
    m = _re.match(r"^(\d+)\s*([mhd])$", duration_str, _re.IGNORECASE)
    if not m:
        return jsonify({"success": False, "error": "Invalid duration (e.g. 7d, 12h, 30m)."}), 400
    n = int(m.group(1))
    mult = {"m": 60, "h": 3600, "d": 86400}[m.group(2).lower()]
    seconds = n * mult
    if seconds <= 0 or seconds > 2419200:  # max 28d
        return jsonify({"success": False, "error": "Duration must be 1m to 28d."}), 400

    # DM before ban
    dm_sent = False
    if want_dm:
        dm_sent = _try_dm(
            member,
            f"🔨 You've been banned from **{guild.name}**\n**Reason:** {reason}\n**Duration:** {duration_str}",
        )

    # Ban via Discord
    try:
        from web.blueprints.moderation import _service
        service = _service()
        run_coro_threadsafe(
            service.ban(guild_id, user_id, reason, 0)
        ).result(timeout=20)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # Store expiration for the sweep task
    import time as _time
    try:
        from cogs.admin_cog import _tempban_data, _save_mod_data
        mod_data, tempbans = _tempban_data(guild_id)
        tempbans[str(user_id)] = {
            "until": _time.time() + seconds,
            "reason": reason,
            "moderator": "Web dashboard",
        }
        _save_mod_data(mod_data)
    except Exception:
        pass

    _, _record_case, _ = _mod_helpers()
    _record_case_direct(
        guild_id, user_id, "ban",
        f"{reason} (tempban: {duration_str})",
        evidence=evidence, dm_sent=dm_sent,
    )

    return jsonify({"success": True, "duration": duration_str, "dm_sent": dm_sent})


# ============================================================
# WIPE DATA
#
# POST /api/servers/<guild_id>/members/<user_id>/wipe
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/wipe"
)
@require_guild_moderator
def modpanel_wipe(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    _mod_record, _record_case, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500

    mod_name, mod_id, _ = _moderator()
    mod_label = f"{mod_name} ({mod_id})" if mod_id else mod_name

    # Unban if banned
    guild, member = _get_member(guild_id, user_id)
    if guild:
        try:
            bans = run_coro_threadsafe(guild.bans()).result(timeout=15)
            for ban_entry in bans:
                if ban_entry.user.id == int(user_id):
                    run_coro_threadsafe(
                        guild.unban(ban_entry.user, reason="Wipe data via web dashboard")
                    ).result(timeout=15)
                    break
        except Exception:
            pass
        # Remove timeout if timed out
        if member:
            try:
                if hasattr(member, "is_timed_out") and member.is_timed_out():
                    run_coro_threadsafe(
                        member.timeout(None, reason="Wipe data via web dashboard")
                    ).result(timeout=15)
            except Exception:
                pass

    # Clear warns/notes/cases from mod_data.json
    mod_data, urec = _mod_record(guild_id, user_id)
    urec["warns"] = []
    urec["notes"] = []
    urec["cases"] = []
    _save_mod_data(mod_data)
    _record_case_direct(
        guild_id, user_id, "wipe",
        "All data wiped via web dashboard (warns, notes, XP, watch, ban, timeout).",
    )

    # Remove watch entry
    wc = _watch_cog()
    if wc and hasattr(wc, "watch_remove"):
        try:
            result = wc.watch_remove(str(guild_id), str(user_id))
            if hasattr(result, "__await__"):
                run_coro_threadsafe(result).result(timeout=15)
        except Exception:
            pass

    # Reset XP — best effort
    try:
        from cogs.Level_system import award_xp
        guild, member = _get_member(guild_id, user_id)
        xp, _ = _xp_for(guild_id, user_id)
        if xp > 0 and guild:
            display = member.display_name if member else str(user_id)
            run_coro_threadsafe(
                award_xp(guild, int(user_id), display, -xp, apply_event=False)
            ).result(timeout=15)
    except Exception:
        pass

    return jsonify({"success": True})
