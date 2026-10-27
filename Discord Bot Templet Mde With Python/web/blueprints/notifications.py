"""Notification center API.

Builds a per-user feed from things the site already knows: moderation
cases filed against the user (warn/timeout/kick/ban) and level-ups from
the profile activity feed. Read state (last-read time) lives in
``data/notification_read.json`` so it survives restarts. Friend requests
and other social notifications will plug into this same feed later.
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


@notifications_api.get(
    "/notifications"
)
@require_login
def get_notifications():

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    if not user_id:

        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    read_ts = int((_read_state().get(user_id) or 0))

    items = _mod_cases(user_id) + _level_ups(user_id)

    items = [n for n in items if n["ts"] > 0]

    items.sort(key=lambda n: n["ts"], reverse=True)

    items = items[:30]

    for n in items:

        n["unread"] = n["ts"] > read_ts

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

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    if not user_id:

        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    state = _read_state()

    state[user_id] = int(time.time())

    _write_state(state)

    return jsonify({

        "success": True,

    })
