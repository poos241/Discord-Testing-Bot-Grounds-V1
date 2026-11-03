import discord
import secrets
from flask import Blueprint, jsonify, render_template, request, session
import json

from web.services.logger_db import logger_db as database
from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.services.event_store import event_store
from web.services.member_service import MemberService


from web.services.statistics import statistics
from web.services.guilds import guilds

from web.services.server_service import ServerService as DashboardService

from web.services.server_service import ServerService

from web.services.event_store import publish_event

from web.blueprints.auth import (get_auth_session, user_can_manage_guild, get_csrf_token)
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


api = Blueprint(
    "api",
    __name__
)


# =========================================================
# BRIDGE HELPERS
#
# Bridge split: there is no live bot object in this process.
# These helpers replace the old "bot = discord_state.bot / if bot
# is None / if not discord_state.ready" pairs, keeping each
# route's exact error strings and status codes.
# =========================================================

def _bot_error(guild_id=None):
    """(response, status) when the bot is down/not ready, else None.

    Bridge unreachable -> "Discord bot is not connected." (503);
    bridge up but bot not ready -> "Discord bot is not ready."
    (503). guild_id is included in the payload when given (some
    routes send it).
    """
    try:
        info = bridge.status()
    except Exception:
        payload = {
            "success": False,
            "error": "Discord bot is not connected.",
        }
        if guild_id is not None:
            payload["guild_id"] = str(guild_id)
        return jsonify(payload), 503
    if not info.get("ready"):
        payload = {
            "success": False,
            "error": "Discord bot is not ready.",
        }
        if guild_id is not None:
            payload["guild_id"] = str(guild_id)
        return jsonify(payload), 503
    return None


def _guild_or_error(guild_id):
    """(guild_dict, None) or (None, (response, status)).

    Guild dicts come from the bridge. A 404 means the bot is not
    in the guild; a 503 means the bot is down/not ready.
    """
    denied = _bot_error(guild_id)
    if denied:
        return None, denied
    try:
        guild = bridge.get_guild(int(guild_id))
    except BridgeUnavailable:
        return None, (jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
        }), 503)
    if guild is None:
        return None, (jsonify({
            "success": False,
            "error": "Discord server not found.",
        }), 404)
    return guild, None


def _perm_names(value):
    """Enabled permission names from a bitfield int (bridge roles
    and guild_permissions are ints; the old code iterated live
    discord.py Permissions objects)."""
    try:
        perms = discord.Permissions(int(value or 0))
    except Exception:
        return []
    return [name for name, enabled in perms if enabled]


# =========================================================
# SYSTEM STATUS
# =========================================================

@api.route("/status")
@require_login
def status():

    # Bridge split: bot identity/latency come from bridge.status().
    # When the bridge is down everything reports disconnected (same
    # shape as the old bot-is-None branch).
    bot_name = None
    bot_id = None
    bot_avatar = None
    connected = False
    ready = False

    try:
        info = bridge.status()
        connected = True
        ready = bool(info.get("ready"))
        user = info.get("user") or {}
        bot_id = user.get("id")
        bot_name = user.get("name")
        bot_avatar = user.get("avatar_url")
    except Exception:
        pass

    return {

        "online":
            True,

        "discord_connected":
            connected,

        "discord_ready":
            ready,

        "bot_name":
            bot_name,

        "bot_id":
            bot_id,

        "bot_avatar":
            bot_avatar,

    }
# =========================================================
# GLOBAL SERVERS
# =========================================================
'''
@api.route("/servers")
@require_login
def servers():

    return {
        "servers": guilds.get_guilds()
    }
'''

# =========================================================
# GLOBAL EVENTS
# =========================================================


@api.route("/events/history")
@require_login
def event_history():

    rows = database.latest_global_events(100)

    results = []


    for row in rows:

        payload = row[7]

        try:

            payload = json.loads(
                payload
            )

        except (
            TypeError,
            json.JSONDecodeError
        ):

            payload = {
                "raw": str(payload)
            }


        results.append({

            "id":
                row[0],

            "guild_id":
                row[1],

            "category":
                row[2] or "unknown",

            "action":
                row[3] or "",

            "event":
                row[4] or "unknown",

            "timestamp":
                row[5] or "",

            "created":
                row[6] or 0,

            "data":
                payload

        })


    return {
        "events": results
    }


# =========================================================
# GLOBAL STATISTICS
# =========================================================

@api.route("/statistics")
@require_login
def statistics_api():

    return statistics.get_global_stats()


@api.route("/stats")
@require_login
def stats():

    rows = database.latest_global_events(
        1000
    )


    categories = {

        "messages": 0,
        "members": 0,
        "roles": 0,
        "voice": 0,
        "server": 0,
        "channels": 0,
        "other": 0

    }


    events = {}

    latest_timestamp = None


    for row in rows:

        category = (
            row[2]
            or "other"
        )

        event_name = (
            row[4]
            or "unknown"
        )

        timestamp = row[5]


        categories[category] = (
            categories.get(
                category,
                0
            ) + 1
        )


        events[event_name] = (
            events.get(
                event_name,
                0
            ) + 1
        )


        if latest_timestamp is None:

            latest_timestamp = timestamp


    return {

        "total":
            len(rows),

        "categories":
            categories,

        "events":
            events,

        "latest_timestamp":
            latest_timestamp

    }


# =========================================================
# SERVER INFORMATION
# =========================================================

@api.route("/servers/<int:guild_id>")
@require_guild_moderator
def server_info(guild_id):

    denied = _bot_error(guild_id)
    if denied:
        return denied

    info = guilds.get_guild_info(
        guild_id
    )


    if info is None:

        return jsonify({

            "success": False,

            "error":
                "Discord server not found.",

            "guild_id":
                str(guild_id)

        }), 404


    return jsonify(info)


# =========================================================
# SERVER OVERVIEW DATA
# =========================================================

@api.get("/servers/<int:guild_id>/overview")
@require_guild_moderator
def server_overview(guild_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    service = MemberService()
    members = service.get_members(guild_id)
    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except Exception:
        channels = []
    try:
        roles = bridge.get_roles(int(guild_id)) or []
    except Exception:
        roles = []

    humans = [
        member
        for member in members
        if not member.get("bot")
    ]

    bots = [
        member
        for member in members
        if member.get("bot")
    ]

    online = [
        member
        for member in members
        if str(member.get("status") or "offline").lower()
        not in (
            "offline",
            "invisible"
        )
    ]

    text_channels = [
        channel
        for channel in channels
        if (channel.get("type") or "") == "text"
    ]

    voice_channels = [
        channel
        for channel in channels
        if (channel.get("type") or "") == "voice"
    ]

    categories = [
        channel
        for channel in channels
        if (channel.get("type") or "") == "category"
    ]

    return jsonify({

        "success": True,

        "server": {

            "id":
                str(guild.get("id")),

            "name":
                guild.get("name"),

            "icon":
                guild.get("icon"),

            "owner_id":
                (
                    str(guild.get("owner_id"))
                    if guild.get("owner_id")
                    else None
                ),

            "created_at":
                guild.get("created_at"),

            "member_count":
                int(guild.get("member_count") or len(members) or 0),

            "channel_count":
                len(channels),

            "role_count":
                len(roles)

        },


        "members": {

            "count":
                len(members),

            "humans":
                len(humans),

            "bots":
                len(bots),

            "online":
                len(online)

        },


        "channels": {

            "count":
                len(channels),

            "text":
                len(text_channels),

            "voice":
                len(voice_channels),

            "categories":
                len(categories)

        },


        "roles": {

            "count":
                len(roles)

        }

    })

# =========================================================
# SERVER EVENTS
# =========================================================


@api.route(
    "/servers/<int:guild_id>/events"
)
@require_guild_moderator
def server_events(guild_id):

    search = request.args.get(
        "search",
        ""
    ).strip()

    category = request.args.get(
        "category"
    )

    try:

        page = max(
            int(
                request.args.get(
                    "page",
                    1
                )
            ),
            1
        )

    except ValueError:

        page = 1

    try:

        per_page = min(
            max(
                int(
                    request.args.get(
                        "limit",
                        25
                    )
                ),
                1
            ),
            100
        )

    except ValueError:

        per_page = 25


    offset = (
        page - 1
    ) * per_page


    total = database.count_events(
        guild_id,
        search=search,
        category=category
    )


    events = database.search_events(
        guild_id,
        search=search,
        category=category,
        limit=per_page,
        offset=offset
    )


    return {
        "events": events,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (
                (total + per_page - 1)
                // per_page
            )
        }
    }

@api.route(
    "/servers/<int:guild_id>/events/<int:event_id>"
)
@require_guild_moderator
def event_details(
    guild_id,
    event_id
):

    event = database.get_event(
        guild_id,
        event_id
    )

    if event is None:

        return {
            "error":
                "Event not found"
        }, 404

    return event


# =========================================================
# SINGLE CHANNEL
# =========================================================

@api.get(
    "/servers/<int:guild_id>/channels/<int:channel_id>"
)
@require_guild_moderator
def server_channel(
    guild_id,
    channel_id
):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503
    channel = None
    for candidate in channels:
        if str(candidate.get("id")) == str(channel_id):
            channel = candidate
            break

    if channel is None:

        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "channel": {

            "id":
                str(channel.get("id")),

            "name":
                channel.get("name"),

            "type":
                channel.get("type"),

            "position":
                channel.get("position", 0),

            "category_id":
                channel.get("category_id"),

            "category":
                channel.get("category"),

            "created_at":
                channel.get("created_at"),

            "mention":
                channel.get("mention")
        }
    })


# =========================================================
# CHANNEL SUMMARY
# =========================================================

@api.get(
    "/servers/<int:guild_id>/channels/summary"
)
@require_guild_moderator
def server_channels_summary(guild_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    def _of_type(*types):
        return [
            channel
            for channel in channels
            if (channel.get("type") or "") in types
        ]

    text_channels = _of_type("text")
    voice_channels = _of_type("voice")
    categories = _of_type("category")
    announcement_channels = _of_type("news")
    stage_channels = _of_type("stage_voice")
    forum_channels = _of_type("forum")

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "summary": {

            "total":
                len(channels),

            "text":
                len(text_channels),

            "voice":
                len(voice_channels),

            "categories":
                len(categories),

            "announcements":
                len(announcement_channels),

            "stage":
                len(stage_channels),

            "forums":
                len(forum_channels)
        }
    })

# =========================================================
@api.route("/csrf", methods=["GET"])
@require_login
def csrf():
    if not get_auth_session():
        return jsonify({"success": False, "error": "Authentication required."}), 401
    return jsonify({"success": True, "csrf_token": get_csrf_token()})


# LOGGER CONFIGURATION
# =========================================================

_LOG_TYPES = (
    "message",
    "voice",
    "member",
    "role",
    "channel",
    "thread",
    "moderation",
    "invite",
    "emoji",
    "sticker",
    "server",
)


def _require_logger_management(guild_id):
    if not get_auth_session():
        return jsonify({"success": False, "error": "Authentication required."}), 401
    if not user_can_manage_guild(guild_id):
        return jsonify({
            "success": False,
            "error": "You do not have permission to manage logger settings for this server."
        }), 403
    return None


@api.route("/servers/<int:guild_id>/logging", methods=["GET"])
@require_guild_moderator
def server_logging(guild_id):
    denied = _require_logger_management(guild_id)
    if denied:
        return denied

    settings = {}
    for log_type in _LOG_TYPES:
        channel_id = database.get_log_channel(guild_id, log_type)
        settings[log_type] = str(channel_id) if channel_id is not None else None

    return jsonify({"success": True, "guild_id": str(guild_id), "logging": settings})


@api.route("/servers/<int:guild_id>/logging/channels", methods=["GET"])
@require_guild_moderator
def logger_channels(guild_id):
    denied = _require_logger_management(guild_id)
    if denied:
        return denied

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not ready."}), 503

    # Text-like channels can receive log messages (the old code kept
    # channels with a .send method: text + news; forum channels can
    # also receive messages).
    channels = []
    for channel in sorted(
        bridge_channels,
        key=lambda c: (
            c.get("position") or 0,
            str(c.get("name") or "").lower(),
        ),
    ):
        if (channel.get("type") or "") not in ("text", "news", "forum"):
            continue
        channels.append({
            "id": str(channel.get("id")),
            "name": str(channel.get("name")),
            "type": str(channel.get("type") or "unknown"),
            "category": channel.get("category"),
        })

    return jsonify({"success": True, "guild_id": str(guild_id), "channels": channels})


@api.route("/servers/<int:guild_id>/logging", methods=["POST"])
@require_guild_moderator
def save_server_logging(guild_id):
    denied = _require_logger_management(guild_id)
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

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({"success": False, "error": "Discord bot is not ready."}), 503

    valid_channels = {
        str(channel.get("id"))
        for channel in bridge_channels
        if (channel.get("type") or "") in ("text", "news", "forum")
    }

    data = request.get_json(silent=True) or {}
    saved = {}

    for log_type in _LOG_TYPES:
        raw = data.get(log_type)
        if raw in (None, "", "none", "null"):
            database.set_log_channel(guild_id, log_type, None)
            saved[log_type] = None
            continue

        channel_id = str(raw).strip()
        if channel_id not in valid_channels:
            return jsonify({
                "success": False,
                "error": f"Invalid channel selected for {log_type}."
            }), 400

        database.set_log_channel(guild_id, log_type, int(channel_id))
        saved[log_type] = channel_id

    return jsonify({"success": True, "guild_id": str(guild_id), "logging": saved})


# SERVER PAGE
# =========================================================

@api.route(
    "/servers/<int:guild_id>/view"
)
@require_guild_moderator
def server_page_view(
    guild_id
):

    return render_template(

        "server.html",

        guild_id=guild_id

    )
    
    
# =========================================================
# MEMBERS PAGE
# =========================================================

@api.route(
    "/servers/<int:guild_id>/members/view"
)
@require_guild_moderator
def server_members_page(guild_id):

    return render_template(
        "members.html",
        guild_id=guild_id
    )
    
# =========================================================
# SERVER DASHBOARD
# =========================================================

@api.get("/servers/<int:guild_id>/dashboard")
@require_guild_moderator
def server_dashboard_data(guild_id):

    denied = _bot_error()
    if denied:
        return denied

    service = DashboardService()

    dashboard = service.get_dashboard(
        guild_id
    )

    if dashboard is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    return jsonify({
        "success": True,
        "guild_id": str(guild_id),
        "dashboard": dashboard
    })
    
    
    
# =========================================================
# EVENTS
# =========================================================

def serialize_event(event):

    if event is None:

        return None


    if isinstance(event, dict):

        return {

            "id":
                str(
                    event.get(
                        "id"
                    )
                )
                if event.get("id") is not None
                else None,

            "category":
                event.get(
                    "category"
                ),

            "event_type":
                (
                    event.get(
                        "event_type"
                    )
                    or
                    event.get(
                        "type"
                    )
                ),

            "guild_id":
                (
                    str(
                        event.get(
                            "guild_id"
                        )
                    )
                    if event.get(
                        "guild_id"
                    ) is not None
                    else None
                ),

            "user_id":
                (
                    str(
                        event.get(
                            "user_id"
                        )
                    )
                    if event.get(
                        "user_id"
                    ) is not None
                    else None
                ),

            "channel_id":
                (
                    str(
                        event.get(
                            "channel_id"
                        )
                    )
                    if event.get(
                        "channel_id"
                    ) is not None
                    else None
                ),

            "data":
                event.get(
                    "data"
                ) or {},

            "timestamp":
                event.get(
                    "timestamp"
                )

        }


    if hasattr(
        event,
        "to_dict"
    ):

        return event.to_dict()


    return {
        "event":
            str(event)
    }

@api.get("/events")
@require_login
def get_events():
    """
    GET /api/events

    Return the most recent events from the event store.
    """

    try:

        events = event_store.latest(100)

        serialized = []

        for event in events:

            try:
                serialized.append(
                    serialize_event(event)
                )

            except Exception as e:

                print(
                    f"[Events API] Failed to serialize event: {e}"
                )

        return jsonify({

            "success": True,

            "count": len(serialized),

            "events": serialized

        })

    except Exception as e:

        print(
            f"[Events API] Failed to retrieve events: {e}"
        )

        return jsonify({

            "success": False,

            "error": str(e),

            "count": 0,

            "events": []

        }), 500
        
        
# =========================================================
# MEMBER DASHBOARD
# =========================================================


    

    
    
# =========================================================
# SERVER HEALTH
# GET /api/servers/<guild_id>/health
# =========================================================

@api.get(
    "/servers/<int:guild_id>/health"
)
@require_guild_moderator
def server_health(
    guild_id
):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        info = bridge.status()
        latency = round(float(info.get("latency_ms") or 0))
    except Exception:
        latency = 0

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except Exception:
        channels = []
    try:
        roles = bridge.get_roles(int(guild_id)) or []
    except Exception:
        roles = []

    member_count = (
        int(guild.get("member_count") or 0)
        or len(MemberService().get_members(guild_id))
        or 0
    )

    text_count = sum(
        1
        for channel in channels
        if str(channel.get("type") or "").lower() == "text"
    )

    voice_count = sum(
        1
        for channel in channels
        if str(channel.get("type") or "").lower() == "voice"
    )

    role_count = len(roles)

    event_count = (
        event_store.count_for_guild(
            guild_id
        )
    )

    recent_events = (
        event_store.for_guild(
            guild_id,
            limit=1
        )
    )

    last_event_at = None

    if (
        recent_events
        and isinstance(
            recent_events[0],
            dict
        )
    ):

        last_event_at = (
            recent_events[0]
            .get(
                "timestamp"
            )
        )

    if latency < 200:

        status = "healthy"

    elif latency < 500:

        status = "degraded"

    else:

        status = "poor"

    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild.get("id")),

        "health": {

            "discord_connected":
                True,

            "discord_ready":
                True,

            "bot_latency_ms":
                latency,

            "status":
                status,

            "members":
                member_count,

            "channels":
                len(channels),

            "text_channels":
                text_count,

            "voice_channels":
                voice_count,

            "roles":
                role_count,

            "events":
                event_count,

            "last_event_at":
                last_event_at,

            "logger":
                (
                    "active"
                    if event_count > 0
                    else "idle"
                ),

            "guild_available":
                guild.get("available", True),

        }

    })


# =========================================================
# CHANNEL DETAILS
# GET /api/servers/<guild_id>/channels/<channel_id>
# =========================================================

@api.get("/servers/<int:guild_id>/channels/<int:channel_id>")
@require_guild_moderator
def channel_details(guild_id, channel_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503
    channel = None
    for candidate in channels:
        if str(candidate.get("id")) == str(channel_id):
            channel = candidate
            break

    if channel is None:
        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404

    data = {
        "id": str(channel.get("id")),
        "name": channel.get("name"),
        "type": str(channel.get("type")),
        "position": channel.get("position"),
        "category_id": channel.get("category_id"),
        "category": channel.get("category"),
        "guild_id": str(guild.get("id")),
        "guild_name": guild.get("name"),
        "created_at": channel.get("created_at"),
    }

    # Type-specific extras, as the old hasattr-gated code sent them.
    if (channel.get("type") or "") in ("text", "news", "forum"):
        data["topic"] = channel.get("topic")
        data["slowmode_delay"] = channel.get("slowmode_delay", 0)
        data["nsfw"] = bool(channel.get("nsfw", False))
    if (channel.get("type") or "") == "voice":
        data["bitrate"] = channel.get("bitrate")
        data["user_limit"] = channel.get("user_limit")

    return jsonify({
        "success": True,
        "channel": data
    })
# =========================================================
# CHANNEL STATISTICS
# GET /api/servers/<guild_id>/channels/summary
# =========================================================

@api.get("/servers/<int:guild_id>/channels/summary")
@require_guild_moderator
def channel_summary(guild_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    text_channels = []
    voice_channels = []
    categories = []
    threads = []
    other = []

    for channel in channels:

        channel_type = str(channel.get("type") or "").lower()

        if channel_type == "text":
            text_channels.append(channel)

        elif channel_type == "voice":
            voice_channels.append(channel)

        elif channel_type == "category":
            categories.append(channel)

        elif "thread" in channel_type:
            threads.append(channel)

        else:
            other.append(channel)

    return jsonify({
        "success": True,

        "guild_id": str(guild.get("id")),

        "guild_name": guild.get("name"),

        "summary": {
            "total": len(channels),

            "text": len(text_channels),

            "voice": len(voice_channels),

            "categories": len(categories),

            "threads": len(threads),

            "other": len(other)
        }
    })


# =========================================================
# ROLE DETAILS
# GET /api/servers/<guild_id>/roles/<role_id>
# =========================================================

@api.get("/servers/<int:guild_id>/roles/<int:role_id>")
@require_guild_moderator
def role_details(guild_id, role_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    try:
        roles = bridge.get_roles(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    role = None
    for candidate in roles:
        if str(candidate.get("id")) == str(role_id):
            role = candidate
            break

    if role is None:
        return jsonify({
            "success": False,
            "error": "Role not found."
        }), 404

    members = MemberService().get_members(guild_id)
    members_with_role = [
        member
        for member in members
        if any(
            str(r.get("id")) == str(role_id)
            for r in (member.get("roles") or [])
        )
    ]

    return jsonify({
        "success": True,

        "role": {
            "id": str(role.get("id")),
            "name": role.get("name"),
            "position": role.get("position"),
            "color": role.get("color"),
            "hoist": role.get("hoist"),
            "mentionable": role.get("mentionable"),
            "managed": role.get("managed"),

            "member_count": len(
                members_with_role
            ),

            "permissions": _perm_names(role.get("permissions")),
        }
    })

# =========================================================
# BOT HEALTH
# GET /api/health
# =========================================================

@api.get("/health")
@require_login
def bot_health():

    # Bridge split: health comes from bridge.status(). Down -> the
    # old offline shape; up-but-not-ready -> "starting".
    try:
        info = bridge.status()
    except Exception:
        return jsonify({

            "success": True,

            "health": {

                "status": "offline",

                "discord_connected":
                    False,

                "discord_ready":
                    False,

                "guild_count":
                    0,

                "latency_ms":
                    None
            }

        })

    latency = info.get("latency_ms")
    latency = round(float(latency)) if latency is not None else None

    if not info.get("ready"):

        status = "starting"

    elif latency is not None and latency < 200:

        status = "healthy"

    elif latency is not None and latency < 500:

        status = "degraded"

    else:

        status = "poor"

    user = info.get("user") or {}

    return jsonify({

        "success": True,

        "health": {

            "status":
                status,

            "discord_connected":
                True,

            "discord_ready":
                bool(info.get("ready")),

            "guild_count":
                int(info.get("guild_count") or 0),

            "latency_ms":
                latency,

            "user":
                (
                    {
                        "id": str(user.get("id")),
                        "name": user.get("name")
                    }
                    if user.get("id")
                    else None
                )
        }

    })

# =========================================================
# API INFO
# GET /api
# =========================================================

@api.get("/")
@require_login
def api_info():

    return jsonify({

        "success": True,

        "name":
            "Kush Bush Discord Dashboard API",

        "version":
            "1.0.0",

        "status":
            "online",

        "discord_ready":
            bridge.bot_is_ready(),

        "endpoints": {

            "status":
                "/api/status",

            "health":
                "/api/health",

            "servers":
                "/api/servers",

            "events":
                "/api/events",

            "members":
                "/api/members",

            "statistics":
                "/api/statistics"
        }

    })
    
    
# =========================================================
# SERVER STATISTICS
# =========================================================

@api.get("/servers/<int:guild_id>/statistics")
@require_guild_moderator
def server_statistics(guild_id):

    denied = _bot_error()
    if denied:
        return denied

    # ServerService.get_statistics is new (the old call site was
    # broken: no such method existed, so this always 500'd).
    service = ServerService()

    statistics = service.get_statistics(guild_id)

    if statistics is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    return jsonify({
        "success": True,
        "statistics": statistics
    })
    
    
# =========================================================
# SERVER EVENT HISTORY
# GET /api/servers/<guild_id>/activity
# =========================================================

@api.get("/servers/<int:guild_id>/activity")
@require_guild_moderator
def server_activity(guild_id):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error


    limit = request.args.get(
        "limit",
        default=100,
        type=int
    )


    limit = max(
        1,
        min(
            limit,
            500
        )
    )


    events = event_store.for_guild(
        int(guild_id),
        limit=limit
    )


    serialized_events = []

    category_counts = {}


    for event in events:

        if isinstance(event, dict):

            item = dict(
                event
            )

        else:

            item = {

                "id":
                    getattr(
                        event,
                        "id",
                        None
                    ),

                "category":
                    getattr(
                        event,
                        "category",
                        "system"
                    ),

                "event_type":
                    getattr(
                        event,
                        "event_type",
                        "unknown"
                    ),

                "guild_id":
                    getattr(
                        event,
                        "guild_id",
                        guild_id
                    ),

                "data":
                    getattr(
                        event,
                        "data",
                        {}
                    ),

                "timestamp":
                    (
                        event.timestamp.isoformat()
                        if getattr(
                            event,
                            "timestamp",
                            None
                        )
                        else None
                    )

            }


        category = str(
                item.get(
                    "category",
                    "system"
                )
                or "system"
            )


        category_counts[
            category
        ] = (
            category_counts.get(
                category,
                0
            ) + 1
        )


        serialized_events.append(
            item
        )


    newest_timestamp = None


    if serialized_events:

        newest_timestamp = serialized_events[0].get(
                "timestamp"
            )


    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "count":
            len(serialized_events),

        "limit":
            limit,

        "newest_timestamp":
            newest_timestamp,

        "category_counts":
            category_counts,

        "events":
            serialized_events

    })

@api.get(
    "/servers/<int:guild_id>/activity/summary"
)
@require_guild_moderator
def server_activity_summary(
    guild_id
):

    guild, error = _guild_or_error(guild_id)
    if error:
        return error

    total_events = (
        event_store.count_for_guild(
            guild_id
        )
    )

    events = event_store.for_guild(
        guild_id,
        limit=100
    )

    event_types = {}

    for event in events:

        if isinstance(event, dict):

            event_type = event.get(
                "event_type"
            )

        else:

            event_type = getattr(
                event,
                "event_type",
                None
            )

        if not event_type:
            event_type = "unknown"

        event_types[event_type] = (
            event_types.get(
                event_type,
                0
            ) + 1
        )

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "server": {
            "id":
                str(guild.get("id")),

            "name":
                guild.get("name")
        },

        "summary": {

            "total_events":
                total_events,

            "returned_events":
                len(events),

            "event_types":
                event_types
        }

    })
    
    
@api.get("/events/test")
@require_login
def test_event_system():

    
   

    event = publish_event(

        category="system",

        event_type="dashboard_test",

        guild_id=None,

        data={
            "message":
                "Event system test event",

            "source":
                "dashboard",

            "test":
                True,
        }
    )

    return jsonify({

        "success":
            True,

        "message":
            "Test event created.",

        "store_count":
            event_store.count(),

        "event":
            event,
    })
    
# =========================================================
# DASHBOARD ANALYTICS
# GET /api/servers/<guild_id>/analytics
# =========================================================

@api.get(
    "/servers/<int:guild_id>/analytics"
)
@require_guild_moderator
def server_analytics(
    guild_id
):

    from collections import Counter
    from datetime import datetime, timezone, timedelta

    guild, error = _guild_or_error(guild_id)
    if error:
        return error


    # =====================================================
    # MEMBERS
    # =====================================================

    members = MemberService().get_members(guild_id)

    human_count = 0
    bot_count = 0

    online_count = 0
    idle_count = 0
    dnd_count = 0
    offline_count = 0

    for member in members:

        if member.get("bot"):

            bot_count += 1

        else:

            human_count += 1


        status = str(
            member.get("status") or "offline"
        ).lower()


        if status == "online":

            online_count += 1

        elif status == "idle":

            idle_count += 1

        elif status == "dnd":

            dnd_count += 1

        else:

            offline_count += 1


    # =====================================================
    # CHANNELS
    # =====================================================

    try:
        channels = bridge.get_channels(int(guild_id)) or []
    except Exception:
        channels = []

    text_channels = sum(
        1
        for channel in channels
        if str(channel.get("type") or "") == "text"
    )

    voice_channels = sum(
        1
        for channel in channels
        if str(channel.get("type") or "") == "voice"
    )

    categories = sum(
        1
        for channel in channels
        if str(channel.get("type") or "") == "category"
    )

    stage_channels = sum(
        1
        for channel in channels
        if str(
            channel.get("type") or ""
        ) == "stage_voice"
    )

    forum_channels = sum(
        1
        for channel in channels
        if str(
            channel.get("type") or ""
        ) == "forum"
    )


    # =====================================================
    # ROLES
    # =====================================================

    try:
        roles = bridge.get_roles(int(guild_id)) or []
    except Exception:
        roles = []

    managed_roles = sum(
        1
        for role in roles
        if role.get("managed")
    )

    custom_roles = sum(
        1
        for role in roles
        if not role.get("managed")
        and role.get("name") != "@everyone"
    )

    administrator_roles = sum(
        1
        for role in roles
        if discord.Permissions(int(role.get("permissions") or 0)).administrator
    )


    # =====================================================
    # EVENTS
    # =====================================================

    events = event_store.all_for_guild(
        guild.get("id")
    )


    now = datetime.now(
        timezone.utc
    )

    one_hour_ago = (
        now -
        timedelta(
            hours=1
        )
    )

    one_day_ago = (
        now -
        timedelta(
            hours=24
        )
    )


    total_events = len(
        events
    )

    last_hour = 0
    last_day = 0

    event_types = Counter()
    event_categories = Counter()

    hourly = [
        0
        for _ in range(24)
    ]


    for event in events:

        event_type = (
            event.get(
                "event_type"
            )
            or
            event.get(
                "type"
            )
            or
            "unknown"
        )

        category = (
            event.get(
                "category"
            )
            or
            "unknown"
        )


        event_types[
            str(
                event_type
            )
        ] += 1


        event_categories[
            str(
                category
            )
        ] += 1


        timestamp = event.get(
            "timestamp"
        )


        if not timestamp:

            continue


        try:

            event_time = datetime.fromisoformat(
                str(
                    timestamp
                ).replace(
                    "Z",
                    "+00:00"
                )
            )


            if event_time.tzinfo is None:

                event_time = event_time.replace(
                    tzinfo=timezone.utc
                )


            if event_time >= one_hour_ago:

                last_hour += 1


            if event_time >= one_day_ago:

                last_day += 1

                hours_ago = int(
                    (
                        now -
                        event_time
                    ).total_seconds()
                    // 3600
                )


                if 0 <= hours_ago < 24:

                    index = (
                        23 -
                        hours_ago
                    )

                    hourly[index] += 1


        except (
            ValueError,
            TypeError
        ):

            continue


    top_event_types = [

        {
            "event_type":
                name,

            "count":
                count
        }

        for name, count
        in event_types.most_common(
            10
        )

    ]


    return jsonify({

        "success":
            True,

        "guild_id":
            str(
                guild.get("id")
            ),

        "generated_at":
            now.isoformat(),

        "members": {

            "total":
                int(guild.get("member_count") or 0)
                or len(members),

            "humans":
                human_count,

            "bots":
                bot_count,

            "online":
                online_count,

            "idle":
                idle_count,

            "dnd":
                dnd_count,

            "offline":
                offline_count

        },

        "channels": {

            "total":
                len(channels),

            "text":
                text_channels,

            "voice":
                voice_channels,

            "stage":
                stage_channels,

            "forum":
                forum_channels,

            "categories":
                categories

        },

        "roles": {

            "total":
                len(roles),

            "custom":
                custom_roles,

            "managed":
                managed_roles,

            "administrator":
                administrator_roles

        },

        "events": {

            "total":
                total_events,

            "last_hour":
                last_hour,

            "last_24_hours":
                last_day,

            "event_types":
                dict(
                    event_types
                ),

            "categories":
                dict(
                    event_categories
                ),

            "top_event_types":
                top_event_types,

            "hourly":
                hourly

        }

    })
