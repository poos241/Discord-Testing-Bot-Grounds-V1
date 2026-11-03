# web/blueprints/modpanel.py
#
# Web version of the /userinfo mini-admin panel.
# Provides member moderation data and actions via the web dashboard.
#
# Bridge split: live Discord work (member lookup, DM, timeout/kick/
# ban/rename/strip-roles/purge/XP) goes through the bot-side bridge
# via ModerationService / bridge. Mod-case data (warns/notes/cases)
# still lives in mod_data.json in bot.db, read/written directly with
# the _mod_record/_save_mod_data helpers from cogs.admin_cog -- those
# are pure storage helpers and import standalone in this process
# (verified by the migration harness import test).
#
# The WatchList cog is NOT used any more: its watch_add/watch_remove
# are Discord slash-command handlers (they take a ctx), so the old
# web code calling them with plain ids never worked. Watch state is
# read/written directly on watchlist_data.json via config.load_json /
# save_json (same store the cog uses). See _watch_put_entry for the
# re-read mitigation and the report for the residual risk: the bot's
# WatchList cog caches the store in memory, so it will not see a
# website-added watch (and may overwrite it on its next save) until
# the bot restarts.
#
# Mod-case writes use _save_mod_record (from moderation.py): re-read
# fresh immediately before the write and retry once when the change
# did not land, narrowing the cross-process last-writer-wins window
# with the bot. Residual risk is named there.

import datetime
import re as _re
import time as _time

from flask import Blueprint, request, jsonify

import secrets

from flask import session

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.services.discord_state import run_coro_threadsafe
from web.services.moderation_service import ModerationService
from web.blueprints.moderation import (
    _save_mod_record,
    _save_tempban,
    _service as _moderation_service,
)
from web.security.decorators import (
    require_guild_access,
    require_guild_moderator,
    require_guild_permission,
)
from web.services.permissions import (
    BAN_MEMBERS,
    MANAGE_MESSAGES,
    MANAGE_NICKNAMES,
    MANAGE_ROLES,
)
from web.blueprints.auth import get_csrf_token


def _record_case_direct(guild_id, user_id, action, reason, evidence=None, dm_sent=False):
    """Record a case directly to mod_data.json with full moderator attribution."""
    try:
        mod_name, mod_id, mod_avatar = _moderator()
        case = {
            "action": action,
            "reason": reason,
            "moderator": mod_name,
            "moderator_id": mod_id,
            "moderator_avatar": mod_avatar,
            "evidence": evidence,
            "dm_sent": dm_sent,
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


def _try_dm(guild_id, user_id, text):
    """Try to DM the member via the bridge. Returns True on success."""
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


def _guild_name(guild):
    """Display name from a bridge guild dict (or 'the server')."""
    if isinstance(guild, dict):
        return guild.get("name") or "the server"
    return "the server"


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
    """Return (guild_dict, member_dict) or (None, None).

    Bridge split: both come from the bot-side bridge, not a live bot
    object. (guild, None) means the server is known but the user is
    not a member of it; (None, None) means the server is unknown or
    the bot is down.
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


def _mod_helpers():
    """Import mod-data helpers from the bot's AdminCog module."""
    try:
        from cogs.admin_cog import _mod_record, _record_case, _save_mod_data
        return _mod_record, _record_case, _save_mod_data
    except Exception as e:
        return None, None, None


# ============================================================
# WATCH LIST — direct store access (no cog in this process)
# ============================================================

WATCHLIST_FILE = "watchlist_data.json"


def _watch_load():
    """Fresh watchlist_data.json, or None when the store cannot be
    read. Fail-closed: load_json raises on a persistent store failure
    instead of returning a stale/empty fallback, so None here must
    never be saved over."""
    try:
        from config import load_json
        data = load_json(WATCHLIST_FILE)
        return data if isinstance(data, dict) else {}
    except Exception:
        return None


def _watch_save(data):
    """Persist the watchlist store; False when the save failed."""
    try:
        from config import save_json
        save_json(WATCHLIST_FILE, data)
        return True
    except Exception:
        return False


def _watch_entry(guild_id, user_id):
    """(store, entry) for one watched user; (None, None) when the
    store could not be read."""
    data = _watch_load()
    if data is None:
        return None, None
    users = (data.get(str(guild_id)) or {}).get("users") or {}
    return data, users.get(str(user_id))


def _watch_put_entry(guild_id, user_id, entry):
    """Write one watch entry with a re-read + one retry (same
    cross-process mitigation as the mod-case writes). Returns True
    when the entry is visible in a fresh load afterwards."""
    data = _watch_load()
    if data is None:
        return False
    grec = data.setdefault(str(guild_id), {})
    grec.setdefault("log_channel_id", None)
    grec.setdefault("users", {})[str(user_id)] = dict(entry)
    if not _watch_save(data):
        return False
    fresh = _watch_load()
    if fresh is None:
        return False
    got = (fresh.get(str(guild_id)) or {}).get("users", {}).get(str(user_id))
    if got == dict(entry):
        return True
    grec = fresh.setdefault(str(guild_id), {})
    grec.setdefault("log_channel_id", None)
    grec.setdefault("users", {})[str(user_id)] = dict(entry)
    return _watch_save(fresh)


def _watch_remove_entry(guild_id, user_id):
    """Remove one watch entry with a re-read + one retry. True when
    the user is not watched afterwards (including already-gone)."""
    data = _watch_load()
    if data is None:
        return False
    users = (data.get(str(guild_id)) or {}).get("users") or {}
    if str(user_id) not in users:
        return True
    del users[str(user_id)]
    if not _watch_save(data):
        return False
    fresh = _watch_load()
    if fresh is None:
        return False
    users = (fresh.get(str(guild_id)) or {}).get("users") or {}
    if str(user_id) not in users:
        return True
    users.pop(str(user_id), None)
    return _watch_save(fresh)


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


def _award_xp_chunked(guild_id, user_id, amount, display_name):
    """Award XP through the bridge, chunked to its +/-1000-per-grant
    clamp so the old any-amount behaviour is kept."""
    service = ModerationService()
    remaining = int(amount)
    while remaining != 0:
        chunk = max(-1000, min(1000, remaining))
        run_coro_threadsafe(
            service.award_xp(guild_id, user_id, chunk, display_name)
        ).result(timeout=20)
        remaining -= chunk


def _timed_out(member):
    """True when a bridge member dict shows an active timeout."""
    until = (member or {}).get("timed_out_until")
    if not until:
        return False
    try:
        end = datetime.datetime.fromisoformat(
            str(until).replace("Z", "+00:00")
        )
        if end.tzinfo is None:
            end = end.replace(tzinfo=datetime.timezone.utc)
        return end > datetime.datetime.now(datetime.timezone.utc)
    except Exception:
        return True


def _role_color_value(color):
    """Role colour as an int, from a '#rrggbb' string or an int."""
    if isinstance(color, str):
        text = color.strip()
        if text.startswith("#"):
            try:
                return int(text[1:], 16)
            except ValueError:
                return 0
        try:
            return int(text)
        except ValueError:
            return 0
    try:
        return int(color or 0)
    except (TypeError, ValueError):
        return 0


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

    # Watch status (direct store read; unreadable store reads as
    # "not watched", same as the old cog-missing path).
    watched = False
    watch_info = None
    try:
        _, watch_rec = _watch_entry(guild_id, user_id)
        if watch_rec:
            watched = True
            watch_info = watch_rec
    except Exception:
        pass

    xp, level = _xp_for(guild_id, user_id)

    # Member info (bridge member dict shape: username/display_name/
    # avatar URL string, ISO joined_at/created_at, roles already
    # excluding @everyone, timed_out_until instead of is_timed_out()).
    minfo = {"id": str(user_id), "is_member": member is not None}
    if member:
        try:
            roles = []
            for r in member.get("roles") or []:
                if r.get("name") == "@everyone":
                    continue
                roles.append({
                    "id": str(r.get("id")),
                    "name": r.get("name"),
                    "color": _role_color_value(r.get("color")),
                })
            minfo.update({
                "name": member.get("username"),
                "display_name": member.get("display_name"),
                "discriminator": "0",
                "avatar": member.get("avatar"),
                "bot": bool(member.get("bot", False)),
                "joined_at": member.get("joined_at"),
                "created_at": member.get("created_at"),
                "roles": roles,
                "timed_out": _timed_out(member),
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
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
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
                guild_id, user_id,
                f"⚠️ You've been warned in **{_guild_name(guild)}**\n**Reason:** {reason}",
            )

    warn = {
        "reason": reason,
        "moderator": mod_label,
        "moderator_id": mod_id,
        "moderator_avatar": mod_avatar,
        "evidence": evidence,
        "dm_sent": dm_sent,
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
    }

    def _mutate(urec):
        urec.setdefault("warns", []).append(warn)

    def _verify(urec):
        return warn in (urec.get("warns") or [])

    urec = _save_mod_record(guild_id, user_id, _mutate, _verify)
    if urec is None:
        return jsonify({
            "success": False,
            "error": "Mod data helpers unavailable.",
        }), 500
    _record_case_direct(guild_id, user_id, "warn", reason,
                        evidence=evidence, dm_sent=dm_sent)

    return jsonify({"success": True, "warn_count": len(urec.get("warns", [])), "dm_sent": dm_sent})


# ============================================================
# NOTES
#
# POST /api/servers/<guild_id>/members/<user_id>/notes
# DELETE /api/servers/<int:guild_id>/members/<user_id>/notes/<int:index>
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/notes"
)
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
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

    note = {
        "text": text,
        "moderator": "Web dashboard",
        "timestamp": datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat(),
    }

    def _mutate(urec):
        urec.setdefault("notes", []).append(note)

    def _verify(urec):
        return note in (urec.get("notes") or [])

    urec = _save_mod_record(guild_id, user_id, _mutate, _verify)
    if urec is None:
        return jsonify({
            "success": False,
            "error": "Mod data helpers unavailable.",
        }), 500

    return jsonify({"success": True, "note_count": len(urec.get("notes", []))})


@modpanel_api.delete(
    "/servers/<int:guild_id>/members/<int:user_id>/notes/<int:index>"
)
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
def modpanel_delete_note(guild_id, user_id, index):
    denied = _check_csrf()
    if denied:
        return denied

    _mod_record, _, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500

    try:
        _, urec0 = _mod_record(guild_id, user_id)
    except Exception:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500
    notes0 = urec0.get("notes", [])
    if index < 0 or index >= len(notes0):
        return jsonify({"success": False, "error": "Note not found."}), 404
    expected_len = len(notes0) - 1

    def _mutate(urec):
        notes = urec.get("notes", [])
        if index < 0 or index >= len(notes):
            raise IndexError("Note not found.")
        notes.pop(index)

    def _verify(urec):
        return len(urec.get("notes", [])) == expected_len

    urec = _save_mod_record(guild_id, user_id, _mutate, _verify)
    if urec is None:
        return jsonify({
            "success": False,
            "error": "Mod data helpers unavailable.",
        }), 500

    return jsonify({"success": True, "note_count": len(urec.get("notes", []))})


# ============================================================
# WATCH / UNWATCH
#
# POST /api/servers/<guild_id>/members/<user_id>/watch
# DELETE /api/servers/<guild_id>/members/<user_id>/watch
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/watch"
)
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
def modpanel_watch(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    data = request.get_json(silent=True) or {}
    reason = (data.get("reason") or "Watched via web dashboard.").strip()

    mod_name, mod_id, _ = _moderator()
    mod_label = f"{mod_name} ({mod_id})" if mod_id else mod_name

    _g, member = _get_member(guild_id, user_id)
    entry = {
        "user_id": str(user_id),
        "username": (member.get("username") if member else None) or str(user_id),
        "display_name": (member.get("display_name") if member else None) or str(user_id),
        "added_by": mod_label,
        "added_by_name": mod_name,
        "added_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "reason": reason,
    }
    store, existing = _watch_entry(guild_id, user_id)
    if store is None:
        # Store unreadable (as opposed to "user simply not watched").
        return jsonify({"success": False, "error": "Watch list unavailable."}), 503
    if isinstance(existing, dict):
        # Already watched: keep the original entry, refresh the
        # reason/attribution (as the old code did after watch_add).
        entry = {**existing, "reason": reason,
                 "added_by": mod_label, "added_by_name": mod_name}
    if not _watch_put_entry(guild_id, user_id, entry):
        return jsonify({"success": False, "error": "Watch list could not be saved."}), 503

    _record_case_direct(guild_id, user_id, "watch", reason)

    return jsonify({"success": True, "watched": True})


@modpanel_api.delete(
    "/servers/<int:guild_id>/members/<int:user_id>/watch"
)
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
def modpanel_unwatch(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    if not _watch_remove_entry(guild_id, user_id):
        return jsonify({"success": False, "error": "Watch list unavailable."}), 503

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
        return _bot_down_response()
    display = (member.get("display_name") if member else None) or str(user_id)

    try:
        _award_xp_chunked(guild_id, user_id, amount, display)
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not reachable."}), 503
    except Exception as e:
        return jsonify({"success": False, "error": f"XP update failed: {e}"}), 500

    _record_case_direct(guild_id, user_id,
                        "add_xp" if amount > 0 else "remove_xp",
                        f"{amount} XP")

    xp, level = _xp_for(guild_id, user_id)
    return jsonify({"success": True, "xp": xp, "level": level})


# ============================================================
# RENAME
#
# POST /api/servers/<guild_id>/members/<user_id>/rename  {nickname}
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<user_id>/rename"
)
@require_guild_permission(MANAGE_NICKNAMES, label="Manage Nicknames permission required.")
def modpanel_rename(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None or member is None:
        if guild is None:
            return _bot_down_response()
        return jsonify({"success": False, "error": "Member not found."}), 404

    data = request.get_json(silent=True) or {}
    nickname = (data.get("nickname") or "").strip() or None  # None resets

    try:
        service = ModerationService()
        run_coro_threadsafe(
            service.rename(guild_id, user_id, nickname)
        ).result(timeout=20)
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not reachable."}), 503
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

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
@require_guild_permission(MANAGE_ROLES, label="Manage Roles permission required.")
def modpanel_strip_roles(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None or member is None:
        if guild is None:
            return _bot_down_response()
        return jsonify({"success": False, "error": "Member not found."}), 404

    try:
        service = ModerationService()
        result = run_coro_threadsafe(
            service.strip_roles(
                guild_id, user_id, "Strip roles via web dashboard"
            )
        ).result(timeout=20)
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not reachable."}), 503
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # Bridge returns removed as [{id, name}, ...] (real bridge) or as
    # plain id strings (harness fake); normalise both to the plain
    # name list the old response (and the frontend) expects, resolving
    # bare ids through the guild's role list.
    removed = []
    if isinstance(result, dict):
        role_names = {}
        try:
            for role in (bridge.get_roles(int(guild_id)) or []):
                role_names[str(role.get("id"))] = role.get("name")
        except Exception:
            role_names = {}
        for entry in result.get("removed") or []:
            if isinstance(entry, dict):
                removed.append(entry.get("name"))
            else:
                removed.append(role_names.get(str(entry), str(entry)))

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
@require_guild_permission(MANAGE_MESSAGES, label="Manage Messages permission required.")
def modpanel_clear(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return _bot_down_response()

    data = request.get_json(silent=True) or {}
    try:
        amount = max(1, min(int(data.get("amount", 10)), 100))
    except (TypeError, ValueError):
        amount = 10

    cleared = 0
    target_id = int(user_id)
    service = ModerationService()
    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except Exception:
        channels = []
    # Old code walked guild.text_channels (TextChannel incl. news).
    # Per-channel permission skips are now bridge-side: a channel the
    # bot cannot purge in answers 403 and is skipped, same outcome.
    for channel in channels:
        if cleared >= amount:
            break
        if (channel.get("type") or "") not in ("text", "news"):
            continue
        try:
            result = run_coro_threadsafe(
                service.purge(
                    guild_id, int(channel["id"]), target_id,
                    min(200, amount - cleared),
                )
            ).result(timeout=30)
            if isinstance(result, dict):
                cleared += int(result.get("deleted") or 0)
        except Exception:
            continue

    _record_case_direct(
        guild_id, user_id, "clear",
        f"Cleared ~{cleared} messages via web dashboard.",
    )

    return jsonify({"success": True, "cleared": cleared})


# ============================================================
# TEMPBAN
#
# POST /api/servers/<guild_id>/members/<user_id>/tempban  {duration, reason}
# Duration like "7d", "12h", "30m". Stored in mod_data.json; the
# bot's 1-minute sweep auto-unbans when it expires.
# ============================================================

@modpanel_api.post(
    "/servers/<int:guild_id>/members/<int:user_id>/tempban"
)
@require_guild_permission(BAN_MEMBERS, label="Ban Members permission required.")
def modpanel_tempban(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    guild, member = _get_member(guild_id, user_id)
    if guild is None:
        return _bot_down_response()

    data = request.get_json(silent=True) or {}
    duration_str = (data.get("duration") or "").strip()
    reason = (data.get("reason") or "No reason provided.").strip()
    want_dm = bool(data.get("dm"))
    evidence = (data.get("evidence") or "").strip() or None

    # Parse duration
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
            guild_id, user_id,
            f"🔨 You've been banned from **{_guild_name(guild)}**\n**Reason:** {reason}\n**Duration:** {duration_str}",
        )

    # Ban via Discord (through the bridge; _service aborts 503 when
    # the bot is down -- called outside the try so the abort is not
    # swallowed into a 500).
    service = _moderation_service()
    try:
        run_coro_threadsafe(
            service.ban(guild_id, user_id, reason, 0)
        ).result(timeout=20)
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not reachable."}), 503
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500

    # Store expiration for the sweep task (best effort; the ban
    # itself already succeeded).
    _save_tempban(guild_id, user_id, {
        "until": _time.time() + seconds,
        "reason": reason,
        "moderator": "Web dashboard",
    })

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
@require_guild_access
def modpanel_wipe(guild_id, user_id):
    denied = _check_csrf()
    if denied:
        return denied

    # Server-side confirmation: the caller must re-type the target's
    # user ID. A client-side confirm() alone is not enough for a wipe.
    data = request.get_json(silent=True) or {}
    if str(data.get("confirm") or "") != str(user_id):
        return jsonify({
            "success": False,
            "error": "Wipe not confirmed: re-type the member's user ID to confirm.",
        }), 400

    _mod_record, _record_case, _save_mod_data = _mod_helpers()
    if not _mod_record:
        return jsonify({"success": False, "error": "Mod data helpers unavailable."}), 500

    # Unban if banned
    guild, member = _get_member(guild_id, user_id)
    if guild:
        try:
            bans = bridge.get_bans(int(guild_id)) or []
            for ban_entry in bans:
                ban_user = (ban_entry or {}).get("user") or {}
                if str(ban_user.get("id")) == str(user_id):
                    service = ModerationService()
                    run_coro_threadsafe(
                        service.unban(guild_id, user_id, "Wipe data via web dashboard")
                    ).result(timeout=15)
                    break
        except Exception:
            pass
        # Remove timeout if timed out
        if member and member.get("timed_out_until"):
            try:
                service = ModerationService()
                run_coro_threadsafe(
                    service.untimeout(guild_id, user_id, "Wipe data via web dashboard")
                ).result(timeout=15)
            except Exception:
                pass

    # Clear warns/notes/cases from mod_data.json
    def _mutate(urec):
        urec["warns"] = []
        urec["notes"] = []
        urec["cases"] = []

    def _verify(urec):
        return (not urec.get("warns")
                and not urec.get("notes")
                and not urec.get("cases"))

    _save_mod_record(guild_id, user_id, _mutate, _verify)
    _record_case_direct(
        guild_id, user_id, "wipe",
        "All data wiped via web dashboard (warns, notes, XP, watch, ban, timeout).",
    )

    # Remove watch entry
    _watch_remove_entry(guild_id, user_id)

    # Reset XP — best effort, chunked to the bridge's +/-1000 clamp.
    try:
        xp, _ = _xp_for(guild_id, user_id)
        if xp > 0 and guild:
            display = (member.get("display_name") if member else None) or str(user_id)
            _award_xp_chunked(guild_id, user_id, -xp, display)
    except Exception:
        pass

    return jsonify({"success": True})
