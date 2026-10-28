"""Notification center API.

Builds a per-user feed from things the site already knows: moderation
cases filed against the user (warn/timeout/kick/ban) and level-ups from
the profile activity feed. Read state lives in
``data/notification_read.json`` so it survives restarts. Friend requests
and other social notifications will plug into this same feed later.

How clearing works (important): notifications are NOT stored rows — they
are recomputed on every GET from their sources (mod cases in
``data/mod_data.json`` and level-up rows in the profile activity
table). Deleting a source record to "clear" a notification would destroy
real mod history / activity history, so clearing never touches the
sources. Instead, clearing records dismissed notification IDs in the
read-state file, and GET filters those IDs out. Because notification IDs
are deterministic (case guild + timestamp + action, level timestamp +
level), a dismissed ID stays dismissed across refreshes and relogins,
while genuinely new notifications (new IDs, newer timestamps) still
show up normally.

Per-user state shape in ``data/notification_read.json`` (old files just
stored an int watermark per user; that is migrated on read):

    {
        "read_ts": <epoch of last Mark-all-read>,
        "read": [<ids marked read one by one>],
        "unread": [<ids marked unread one by one>],
        "dismissed": [<ids cleared/dismissed, never shown again>],
    }

An item is unread when (its timestamp is newer than ``read_ts`` OR its
id is in ``unread``) AND its id is not in ``read``. Lists are capped so
the file cannot grow without bound.
"""

import json
import os
import secrets
import time
from datetime import datetime, timezone

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from web.blueprints.auth import get_csrf_token, get_user_guilds
from web.security.decorators import require_login
from web.services.discord_state import run_coro_threadsafe


notifications_api = Blueprint(
    "notifications",
    __name__,
    url_prefix="/api",
)


DATA_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
    )
)
READ_PATH = os.path.join(
    DATA_DIR,
    "notification_read.json",
)

# Max ids kept per per-item list, so the state file stays small. The
# feed itself shows at most 30 items, so 500 is generous headroom.
_MAX_IDS = 500

ACTION_TEXT = {
    "warn": ("You were warned", "⚠️"),
    "warning": ("You were warned", "⚠️"),
    "timeout": ("You were timed out", "🔇"),
    "mute": ("You were timed out", "🔇"),
    "kick": ("You were kicked", "👢"),
    "ban": ("You were banned", "🔨"),
    "tempban": ("You were temporarily banned", "🔨"),
    "unban": ("You were unbanned", "✅"),
}


def _read_state():

    try:

        with open(READ_PATH, encoding="utf-8") as fh:

            data = json.load(fh)

        return data if isinstance(data, dict) else {}

    except Exception:

        return {}


def _write_state(state):

    try:

        os.makedirs(DATA_DIR, exist_ok=True)

        tmp = READ_PATH + ".tmp"

        with open(tmp, "w", encoding="utf-8") as fh:

            json.dump(state, fh)

        os.replace(tmp, READ_PATH)

    except Exception as exc:

        print(
            "[Notifications API] Failed to save read state: "
            f"{exc}"
        )


def _user_state(state, user_id):
    """Normalized per-user state dict (legacy int -> watermark dict).

    Returns a fresh dict; callers must write it back with
    _save_user_state for changes to persist.
    """

    raw = state.get(user_id)

    if isinstance(raw, (int, float)):

        return {
            "read_ts": int(raw),
            "read": [],
            "unread": [],
            "dismissed": [],
        }

    if isinstance(raw, dict):

        out = {
            "read_ts": int(raw.get("read_ts") or 0),
            "read": [],
            "unread": [],
            "dismissed": [],
        }

        for key in ("read", "unread", "dismissed"):

            value = raw.get(key)

            if isinstance(value, list):

                out[key] = [
                    str(v) for v in value if isinstance(v, str) and v
                ][-_MAX_IDS:]

        return out

    return {
        "read_ts": 0,
        "read": [],
        "unread": [],
        "dismissed": [],
    }


def _save_user_state(state, user_id, ust):
    """Persist one user's normalized state, capping per-item lists."""

    for key in ("read", "unread", "dismissed"):

        ust[key] = list(dict.fromkeys(ust.get(key) or []))[-_MAX_IDS:]

    state[user_id] = {
        "read_ts": int(ust.get("read_ts") or 0),
        "read": ust["read"],
        "unread": ust["unread"],
        "dismissed": ust["dismissed"],
    }

    _write_state(state)


def _iso_to_epoch(value):

    if isinstance(value, (int, float)):

        return int(value)

    if isinstance(value, str):

        try:

            dt = datetime.fromisoformat(value)

            if dt.tzinfo is None:

                dt = dt.replace(tzinfo=timezone.utc)

            return int(dt.timestamp())

        except Exception:

            return 0

    return 0


def _mod_cases(user_id):

    """All mod cases filed against user_id across their guilds."""

    try:

        from cogs.admin_cog import _mod_record

    except Exception:

        return []

    try:

        guilds = get_user_guilds() or []

    except Exception:

        guilds = []

    name_by_id = {}

    for g in guilds:

        if isinstance(g, dict) and g.get("id"):

            name_by_id[str(g["id"])] = g.get("name", "a server")

    out = []

    for gid in list(name_by_id):

        try:

            _, urec = _mod_record(str(gid), str(user_id))

            cases = (urec or {}).get("cases", [])

        except Exception:

            continue

        for c in cases:

            if not isinstance(c, dict):

                continue

            action = str(c.get("action", "")).lower()

            title, icon = ACTION_TEXT.get(action, ("Moderation action", "🛡️"))

            text = c.get("reason") or ""

            if c.get("moderator"):

                text = (text + " — by " + c["moderator"]) if text else ("By " + c["moderator"])

            out.append({

                "id": "case-" + gid + "-" + str(_iso_to_epoch(c.get("timestamp"))) + "-" + action,

                "icon": icon,

                "title": title,

                "text": text,

                "guild_name": name_by_id[gid],

                "ts": _iso_to_epoch(c.get("timestamp")),

            })

    return out


def _level_ups(user_id):

    try:

        from data.DB.Storage.storage import get_activity

        rows = run_coro_threadsafe(
            get_activity(str(user_id), 20)
        ).result(timeout=10)

    except Exception:

        return []

    out = []

    for a in rows or []:

        if (a or {}).get("kind") != "level_up":

            continue

        detail = (a or {}).get("detail") or {}

        level = detail.get("level", "?")

        out.append({

            "id": "level-" + str(a.get("ts", 0)) + "-" + str(level),

            "icon": "🎉",

            "title": "You reached level " + str(level) + "!",

            "text": "",

            "guild_name": "",

            "ts": int(a.get("ts") or 0),

        })

    return out


def _friend_requests(user_id):
    """Pending incoming friend requests as bell items.

    Dismissing one of these only hides the bell item (recorded in
    notification_read.json) — the request itself stays pending until
    it is accepted, declined, or auto-declined by the opt-out toggle.
    Accepting/declining removes the row from pending, so it drops
    out of the feed on its own.
    """

    try:
        from data.DB.Storage.storage import list_incoming_pending_friends

        rows = run_coro_threadsafe(
            list_incoming_pending_friends(str(user_id))
        ).result(timeout=10)
    except Exception:
        return []

    out = []
    for r in rows or []:
        name = (r or {}).get("requester_name") or "Someone"
        out.append({
            "id": "friend-" + str(r.get("id")),
            "icon": "\U0001f44b",
            "title": name + " sent you a friend request",
            "text": "Accept or decline it here or on your profile.",
            "guild_name": "",
            "ts": int(r.get("created_ts") or 0),
            "type": "friend",
            "friend_request_id": r.get("id"),
        })
    return out


def _full_feed(user_id):
    """Every computable notification, newest first, before any cap.

    Used by GET (which then caps at 30 after filtering) and by Clear,
    which must dismiss the whole list — not just the visible page —
    so older items cannot slide into view afterwards.
    """

    items = _mod_cases(user_id) + _level_ups(user_id) + _friend_requests(user_id)

    items = [n for n in items if n["ts"] > 0]

    items.sort(key=lambda n: n["ts"], reverse=True)

    for n in items:
        if "type" not in n:
            n["type"] = "level" if n["id"].startswith("level-") else "mod"

    return items


def _is_unread(item, ust):

    if item["id"] in ust["read"]:

        return False

    if item["id"] in ust["unread"]:

        return True

    return item["ts"] > ust["read_ts"]


def _visible_feed(user_id, ust):
    """Full feed minus dismissed items, with unread flags applied."""

    dismissed = set(ust["dismissed"])

    out = []

    for n in _full_feed(user_id):

        if n["id"] in dismissed:

            continue

        n["unread"] = _is_unread(n, ust)

        out.append(n)

    return out


def _current_user_id():
    user = session.get("user") or {}

    return str(user.get("id", ""))


def _require_user():
    """Returns (user_id, error_response) — error_response is None on ok."""

    user_id = _current_user_id()

    if not user_id:

        return "", (jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401)

    return user_id, None


def _check_csrf():
    """Returns an error response when the CSRF token is bad, else None."""

    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()

    expected = get_csrf_token()

    if not supplied or not secrets.compare_digest(supplied, expected):

        return jsonify({
            "success": False,
            "error": "Invalid CSRF token.",
        }), 403

    return None


def _json_body():
    body = request.get_json(silent=True)

    return body if isinstance(body, dict) else {}


@notifications_api.get(
    "/notifications"
)
@require_login
def get_notifications():

    user_id, err = _require_user()

    if err:

        return err

    state = _read_state()

    ust = _user_state(state, user_id)

    items = _visible_feed(user_id, ust)[:30]

    return jsonify({

        "success": True,

        "notifications": items,

        "unread": sum(1 for n in items if n["unread"]),

    })


@notifications_api.post(
    "/notifications/read"
)
@require_login
def mark_read():

    csrf_err = _check_csrf()

    if csrf_err:

        return csrf_err

    user_id, err = _require_user()

    if err:

        return err

    state = _read_state()

    ust = _user_state(state, user_id)

    # Bulk read: move the watermark to now and drop per-item unread
    # overrides. The dismissed list is deliberately left alone, and the
    # per-item read list is kept (harmless, bounded) so items stamped
    # in the future stay read. Never overwrite the whole user entry
    # with a bare int — that would wipe dismissals.
    ust["read_ts"] = int(time.time())

    ust["unread"] = []

    _save_user_state(state, user_id, ust)

    return jsonify({

        "success": True,

    })


@notifications_api.post(
    "/notifications/dismiss"
)
@require_login
def dismiss_one():

    csrf_err = _check_csrf()

    if csrf_err:

        return csrf_err

    user_id, err = _require_user()

    if err:

        return err

    notif_id = str(_json_body().get("id") or "")

    if not notif_id:

        return jsonify({
            "success": False,
            "error": "Missing notification id.",
        }), 400

    state = _read_state()

    ust = _user_state(state, user_id)

    if notif_id not in ust["dismissed"]:

        ust["dismissed"].append(notif_id)

    # A dismissed item needs no read/unread override anymore.
    ust["read"] = [v for v in ust["read"] if v != notif_id]

    ust["unread"] = [v for v in ust["unread"] if v != notif_id]

    _save_user_state(state, user_id, ust)

    return jsonify({

        "success": True,

    })


@notifications_api.post(
    "/notifications/mark"
)
@require_login
def mark_one():

    csrf_err = _check_csrf()

    if csrf_err:

        return csrf_err

    user_id, err = _require_user()

    if err:

        return err

    body = _json_body()

    notif_id = str(body.get("id") or "")

    if not notif_id:

        return jsonify({
            "success": False,
            "error": "Missing notification id.",
        }), 400

    # Only a real JSON true counts as "mark unread"; anything else
    # (false, missing, junk) means "mark read". bool("false") is True
    # in Python, so never use bool() on the raw value here.
    mark_unread = body.get("unread") is True

    state = _read_state()

    ust = _user_state(state, user_id)

    if mark_unread:

        ust["read"] = [v for v in ust["read"] if v != notif_id]

        if notif_id not in ust["unread"]:

            ust["unread"].append(notif_id)

    else:

        ust["unread"] = [v for v in ust["unread"] if v != notif_id]

        if notif_id not in ust["read"]:

            ust["read"].append(notif_id)

    _save_user_state(state, user_id, ust)

    return jsonify({

        "success": True,

    })


@notifications_api.post(
    "/notifications/clear"
)
@require_login
def clear_notifications():

    csrf_err = _check_csrf()

    if csrf_err:

        return csrf_err

    user_id, err = _require_user()

    if err:

        return err

    scope = str(_json_body().get("scope") or "")

    if scope not in ("all", "read"):

        return jsonify({
            "success": False,
            "error": "Scope must be 'all' or 'read'.",
        }), 400

    state = _read_state()

    ust = _user_state(state, user_id)

    # Dismiss from the FULL feed, not just the 30 shown: otherwise an
    # older item would slide into view right after clearing.
    feed = _visible_feed(user_id, ust)

    if scope == "all":

        targets = [n["id"] for n in feed]

    else:

        targets = [n["id"] for n in feed if not n["unread"]]

    dismissed = set(ust["dismissed"])

    added = 0

    for notif_id in targets:

        if notif_id not in dismissed:

            dismissed.add(notif_id)

            added += 1

    ust["dismissed"] = list(dismissed)

    # Cleared items need no read/unread overrides anymore.
    target_set = set(targets)

    ust["read"] = [v for v in ust["read"] if v not in target_set]

    ust["unread"] = [v for v in ust["unread"] if v not in target_set]

    _save_user_state(state, user_id, ust)

    return jsonify({

        "success": True,

        "dismissed": added,

    })
