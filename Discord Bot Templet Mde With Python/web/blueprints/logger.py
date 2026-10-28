from __future__ import annotations

import csv
import io
from datetime import datetime, timezone

from flask import Blueprint, Response, jsonify, request, session

from web.services.event_store import event_store
from web.blueprints.auth import get_auth_session, user_can_manage_guild
from web.security.decorators import require_guild_access, require_guild_manage, require_login

logger_api = Blueprint("logger_api", __name__, url_prefix="/api")


def _require_logger_access(guild_id):
    if not get_auth_session():
        return jsonify({"success": False, "error": "Authentication required."}), 401
    if not user_can_manage_guild(guild_id):
        return jsonify({"success": False, "error": "You do not have permission to view the logger for this server."}), 403
    return None


def _int_arg(name, default, minimum, maximum):
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _filters():
    return {
        "category": request.args.get("category") or None,
        "event_type": request.args.get("event_type") or None,
        "user_id": request.args.get("user_id") or None,
        "channel_id": request.args.get("channel_id") or None,
        "search": (request.args.get("search") or "").strip() or None,
        "date_from": (request.args.get("from") or "").strip() or None,
        "date_to": (request.args.get("to") or "").strip() or None,
    }


@logger_api.get("/servers/<int:guild_id>/logger/summary")
@require_guild_access
def logger_summary(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    breakdown = event_store.guild_breakdown(guild_id)
    return jsonify({
        "success": True,
        "guild_id": str(guild_id),
        "total": event_store.count_for_guild(guild_id),
        "categories": breakdown["categories"],
        "event_types": breakdown["event_types"],
        "recent": event_store.for_guild(guild_id, limit=10),
    })


@logger_api.get("/servers/<int:guild_id>/logger/options")
@require_guild_access
def logger_options(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    return jsonify({"success": True, "guild_id": str(guild_id), **event_store.guild_event_options(guild_id)})


@logger_api.get("/servers/<int:guild_id>/logger/trend")
@require_guild_access
def logger_trend(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    hours = _int_arg("hours", 24, 1, 168)
    return jsonify({
        "success": True,
        "guild_id": str(guild_id),
        "hours": hours,
        "trend": event_store.guild_trend(guild_id, hours),
        "categories": event_store.guild_category_trend(guild_id, hours),
    })


@logger_api.get("/servers/<int:guild_id>/logger/events")
@require_guild_access
def logger_events(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    page = _int_arg("page", 1, 1, 100000)
    per_page = _int_arg("limit", 50, 1, 100)
    result = event_store.query_page(page=page, per_page=per_page, guild_id=guild_id, **_filters())
    return jsonify({"success": True, "guild_id": str(guild_id), **result})


@logger_api.get("/servers/<int:guild_id>/logger/events/<int:event_id>")
@require_guild_access
def logger_event_detail(guild_id, event_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    event = event_store.get(guild_id, event_id)
    if event is None:
        return jsonify({"success": False, "error": "Logger event not found."}), 404
    return jsonify({"success": True, "guild_id": str(guild_id), "event": event})


@logger_api.get("/servers/<int:guild_id>/logger/export")
@require_guild_access
def logger_export(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied

    filters = _filters()
    # Same filters the Logger history page sends: category, event type,
    # search text, user ID, channel ID, and from/to dates. User/channel
    # match the recorded summary text (raw IDs in mentions and field
    # values); events recorded before the Logger summary enrichment
    # have NULL summaries and cannot match a user/channel filter.
    events = event_store.export_guild(guild_id, **filters)
    output = io.StringIO()
    # BOM so Excel opens the UTF-8 CSV with emoji intact.
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow(["id", "guild_id", "timestamp", "category",
                     "event_type", "summary"])
    for event in events:
        writer.writerow([
            event.get("id"), event.get("guild_id"), event.get("timestamp"),
            event.get("category"), event.get("event_type"),
            event.get("summary") or "",
        ])

    filename = (f"logger-{guild_id}-"
                f"{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}")
    user_filter = filters.get("user_id") or ""
    if user_filter.isdigit():
        filename += f"-user-{user_filter}"
    filename += ".csv"
    return Response(
        output.getvalue(),
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ============================================================
# EVENT TOGGLES
#
# GET /api/servers/<guild_id>/logger/toggles
# POST /api/servers/<guild_id>/logger/toggles  {event_key, enabled}
# ============================================================

@logger_api.get("/servers/<int:guild_id>/logger/toggles")
@require_guild_access
def logger_toggles(guild_id):
    from web.services.logger_db import logger_db
    from cogs.Logger.config import EVENT_GROUPS

    groups = {}
    for group_name, events in EVENT_GROUPS.items():
        groups[group_name] = [
            {
                "key": ev,
                "label": ev.replace("_", " ").title(),
                "enabled": bool(logger_db.is_enabled(guild_id, ev)),
            }
            for ev in events
        ]

    return jsonify({"success": True, "groups": groups})


@logger_api.post("/servers/<int:guild_id>/logger/toggles")
@require_guild_access
def logger_set_toggle(guild_id):
    import secrets
    from web.blueprints.auth import get_csrf_token
    from web.services.logger_db import logger_db
    from cogs.Logger.config import ALL_EVENTS

    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 403

    data = request.get_json(silent=True) or {}
    event_key = data.get("event_key")
    enabled = bool(data.get("enabled", True))

    if event_key not in ALL_EVENTS:
        return jsonify({"success": False, "error": "Unknown event key."}), 400

    # set_enabled lives on the real Logger db, not the adapter
    from cogs.Logger.database import db as logger_real_db
    logger_real_db.set_enabled(guild_id, event_key, enabled)

    return jsonify({"success": True, "event_key": event_key, "enabled": enabled})

# ============================================================
# AUTOMOD SETTINGS
#
# GET /api/servers/<guild_id>/logger/automod
# POST /api/servers/<guild_id>/logger/automod
#   {spam_enabled, invites_enabled, external_links_enabled,
#    caps_enabled, spam_threshold, spam_window_seconds}
# Same mod gate as the Logger toggles above (Manage Server on the
# guild) and the same CSRF check. Reads/writes the automod_config
# row through the storage helpers, on the bot loop -- so the web
# page and the /automod commands always see the same values.
# ============================================================

_AUTOMOD_BOOL_KEYS = (
    "spam_enabled",
    "invites_enabled",
    "external_links_enabled",
    "caps_enabled",
)


def _automod_db(call, *args):
    from web.services.discord_state import run_coro_threadsafe
    return run_coro_threadsafe(call(*args)).result(timeout=15)


@logger_api.get("/servers/<int:guild_id>/logger/automod")
@require_guild_access
def logger_automod_get(guild_id):
    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    try:
        from data.DB.Storage.storage import get_automod_config
        cfg = _automod_db(get_automod_config, str(guild_id))
    except Exception as exc:
        return jsonify({"success": False,
                        "error": f"Automod settings unavailable: {exc}"}), 503
    return jsonify({"success": True, "guild_id": str(guild_id),
                    "automod": cfg})


@logger_api.post("/servers/<int:guild_id>/logger/automod")
@require_guild_access
def logger_automod_set(guild_id):
    import secrets
    from web.blueprints.auth import get_csrf_token

    denied = _require_logger_access(guild_id)
    if denied:
        return denied
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return jsonify({"success": False, "error": "Invalid CSRF token."}), 403

    data = request.get_json(silent=True) or {}
    payload = {}
    for key in _AUTOMOD_BOOL_KEYS:
        if key in data:
            payload[key] = bool(data[key])
    threshold = data.get("spam_threshold")
    if threshold is not None:
        try:
            threshold = int(threshold)
        except (TypeError, ValueError):
            return jsonify({"success": False,
                            "error": "spam_threshold must be a number."}), 400
        if not 1 <= threshold <= 50:
            return jsonify({"success": False,
                            "error": "spam_threshold must be between 1 and 50."}), 400
        payload["spam_threshold"] = threshold
    window = data.get("spam_window_seconds")
    if window is not None:
        try:
            window = int(window)
        except (TypeError, ValueError):
            return jsonify({"success": False,
                            "error": "spam_window_seconds must be a number."}), 400
        if not 5 <= window <= 300:
            return jsonify({"success": False,
                            "error": "spam_window_seconds must be between 5 and 300."}), 400
        payload["spam_window_seconds"] = window
    if not payload:
        return jsonify({"success": False,
                        "error": "No automod settings supplied."}), 400
    try:
        from data.DB.Storage.storage import (
            get_automod_config, save_automod_config)
        _automod_db(save_automod_config, str(guild_id), payload)
        cfg = _automod_db(get_automod_config, str(guild_id))
    except Exception as exc:
        return jsonify({"success": False,
                        "error": f"Automod settings unavailable: {exc}"}), 503
    return jsonify({"success": True, "guild_id": str(guild_id),
                    "automod": cfg})
