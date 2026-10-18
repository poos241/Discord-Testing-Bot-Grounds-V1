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

    events = event_store.export_guild(guild_id, **_filters())
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "event_id", "timestamp", "category", "event_type", "user_id", "channel_id", "payload"])
    for event in events:
        writer.writerow([
            event.get("id"), event.get("event_id"), event.get("timestamp"),
            event.get("category"), event.get("event_type"), event.get("user_id"),
            event.get("channel_id"), event.get("data", {}),
        ])

    filename = f"logger-{guild_id}-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}.csv"
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
