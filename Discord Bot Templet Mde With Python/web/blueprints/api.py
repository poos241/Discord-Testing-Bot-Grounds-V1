import discord
import secrets
from flask import Blueprint, jsonify, render_template, request, session
import json

from web.services.logger_db import logger_db as database
from web.services.discord_state import discord_state
from web.services.event_store import event_store


from web.services.statistics import statistics
from web.services.guilds import guilds

from web.services.server_service import ServerService as DashboardService

from web.services.server_service import ServerService

from web.services.event_store import publish_event

from web.blueprints.auth import (get_auth_session, user_can_manage_guild, get_csrf_token)
from web.security.decorators import require_guild_access, require_guild_manage, require_login


api = Blueprint(
    "api",
    __name__
)


# =========================================================
# SYSTEM STATUS
# =========================================================

@api.route("/status")
@require_login
def status():

    bot = discord_state.bot

    connected = (
        bot is not None
    )

    ready = (
        connected
        and discord_state.ready
        and bot.is_ready()
    )


    bot_data = None


    if (
        bot is not None
        and bot.user is not None
    ):

        avatar = None

        try:

            avatar = str(
                bot.user.display_avatar.url
            )

        except Exception:

            avatar = None


        bot_data = {

            "id":
                str(
                    bot.user.id
                ),

            "name":
                str(
                    bot.user
                ),

            "username":
                getattr(
                    bot.user,
                    "name",
                    None
                ),

            "avatar":
                avatar

        }


    bot_avatar = None
    bot_name = None
    bot_id = None


    if bot is not None:

        bot_name = (
            str(bot.user.name)
            if bot.user
            else None
        )

        bot_id = (
            str(bot.user.id)
            if bot.user
            else None
        )

        if bot.user:

            try:

                bot_avatar = str(
                    bot.user.display_avatar.url
                )

            except Exception:

                bot_avatar = None


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
@require_guild_access
@require_guild_manage
def server_info(guild_id):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "guild_id": str(guild_id)
        }), 503

    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready.",
            "guild_id": str(guild_id)
        }), 503


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
@require_guild_access
@require_guild_manage
def server_overview(guild_id):

    bot = discord_state.bot

    if bot is None:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    if not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )


    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    members = list(
        guild.members
    )


    humans = [
        member
        for member in members
        if not member.bot
    ]


    bots = [
        member
        for member in members
        if member.bot
    ]


    online = [
        member
        for member in members
        if member.status
        not in (
            discord.Status.offline,
            discord.Status.invisible
        )
    ]


    text_channels = [
        channel
        for channel in guild.channels
        if isinstance(
            channel,
            discord.TextChannel
        )
    ]


    voice_channels = [
        channel
        for channel in guild.channels
        if isinstance(
            channel,
            discord.VoiceChannel
        )
    ]


    categories = [
        channel
        for channel in guild.channels
        if isinstance(
            channel,
            discord.CategoryChannel
        )
    ]


    return jsonify({

        "success": True,

        "server": {

            "id":
                str(guild.id),

            "name":
                guild.name,

            "icon":
                (
                    guild.icon.url
                    if guild.icon
                    else None
                ),

            "owner_id":
                (
                    str(guild.owner_id)
                    if guild.owner_id
                    else None
                ),

            "created_at":
                guild.created_at.isoformat(),

            "member_count":
                guild.member_count,

            "channel_count":
                len(guild.channels),

            "role_count":
                len(guild.roles)

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
                len(guild.channels),

            "text":
                len(text_channels),

            "voice":
                len(voice_channels),

            "categories":
                len(categories)

        },


        "roles": {

            "count":
                len(guild.roles)

        }

    })

# =========================================================
# SERVER EVENTS
# =========================================================


@api.route(
    "/servers/<int:guild_id>/events"
)
@require_guild_access
@require_guild_manage
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
@require_guild_access
@require_guild_manage
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
@require_guild_access
@require_guild_manage
def server_channel(
    guild_id,
    channel_id
):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    channel = guild.get_channel(
        int(channel_id)
    )

    if channel is None:

        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "channel": {

            "id":
                str(channel.id),

            "name":
                channel.name,

            "type":
                str(channel.type),

            "position":
                getattr(
                    channel,
                    "position",
                    0
                ),

            "category_id": (
                str(channel.category_id)
                if getattr(
                    channel,
                    "category_id",
                    None
                )
                else None
            ),

            "category": (
                channel.category.name
                if getattr(
                    channel,
                    "category",
                    None
                )
                else None
            ),

            "created_at": (
                channel.created_at.isoformat()
                if getattr(
                    channel,
                    "created_at",
                    None
                )
                else None
            ),

            "mention": (
                channel.mention
                if hasattr(
                    channel,
                    "mention"
                )
                else None
            )
        }
    })


# =========================================================
# CHANNEL SUMMARY
# =========================================================

@api.get(
    "/servers/<int:guild_id>/channels/summary"
)
@require_guild_access
@require_guild_manage
def server_channels_summary(guild_id):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    channels = guild.channels

    text_channels = [
        channel
        for channel in channels
        if str(channel.type) == "text"
    ]

    voice_channels = [
        channel
        for channel in channels
        if str(channel.type) == "voice"
    ]

    categories = [
        channel
        for channel in channels
        if str(channel.type) == "category"
    ]

    announcement_channels = [
        channel
        for channel in channels
        if str(channel.type) == "news"
    ]

    stage_channels = [
        channel
        for channel in channels
        if str(channel.type) == "stage_voice"
    ]

    forum_channels = [
        channel
        for channel in channels
        if str(channel.type) == "forum"
    ]

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

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
@require_guild_access
@require_guild_manage
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
@require_guild_access
@require_guild_manage
def logger_channels(guild_id):
    denied = _require_logger_management(guild_id)
    if denied:
        return denied

    bot = discord_state.bot
    if bot is None or not discord_state.ready:
        return jsonify({"success": False, "error": "Discord bot is not ready."}), 503

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return jsonify({"success": False, "error": "Discord server not found."}), 404

    channels = []
    for channel in sorted(guild.channels, key=lambda c: (getattr(c, "position", 0), str(c.name).lower())):
        if not hasattr(channel, "send"):
            continue
        channels.append({
            "id": str(channel.id),
            "name": str(channel.name),
            "type": str(getattr(channel, "type", "unknown")),
            "category": getattr(getattr(channel, "category", None), "name", None),
        })

    return jsonify({"success": True, "guild_id": str(guild_id), "channels": channels})


@api.route("/servers/<int:guild_id>/logging", methods=["POST"])
@require_guild_access
@require_guild_manage
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

    bot = discord_state.bot
    if bot is None or not discord_state.ready:
        return jsonify({"success": False, "error": "Discord bot is not ready."}), 503

    guild = bot.get_guild(int(guild_id))
    if guild is None:
        return jsonify({"success": False, "error": "Discord server not found."}), 404

    valid_channels = {
        str(channel.id): channel
        for channel in guild.channels
        if hasattr(channel, "send")
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
@require_guild_access
@require_guild_manage
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
@require_guild_access
@require_guild_manage
def server_members_page(guild_id):

    return render_template(
        "members.html",
        guild_id=guild_id
    )
    
# =========================================================
# SERVER DASHBOARD
# =========================================================

@api.get("/servers/<int:guild_id>/dashboard")
@require_guild_access
@require_guild_manage
def server_dashboard_data(guild_id):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    service = DashboardService(bot)

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
@require_guild_access
@require_guild_manage
def server_health(
    guild_id
):

    bot = discord_state.bot


    if bot is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected.",

        }), 503


    if (
        not discord_state.ready
        or not bot.is_ready()
    ):

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not ready.",

        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found.",

        }), 404


    latency = round(
        bot.latency * 1000
    )


    member_count = (
        guild.member_count
        or len(
            guild.members
        )
        or 0
    )


    channels = list(
        guild.channels
    )


    text_count = sum(

        1

        for channel
        in channels

        if str(
            channel.type
        ).lower()
        == "text"

    )


    voice_count = sum(

        1

        for channel
        in channels

        if str(
            channel.type
        ).lower()
        == "voice"

    )


    role_count = len(
        guild.roles
    )


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
            str(guild.id),

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
                getattr(
                    guild,
                    "available",
                    True
                ),

        }

    })


# =========================================================
# CHANNEL DETAILS
# GET /api/servers/<guild_id>/channels/<channel_id>
# =========================================================

@api.get("/servers/<int:guild_id>/channels/<int:channel_id>")
@require_guild_access
@require_guild_manage
def channel_details(guild_id, channel_id):

    bot = discord_state.bot

    if bot is None:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(guild_id)

    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    channel = guild.get_channel(channel_id)

    if channel is None:
        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404

    category = getattr(channel, "category", None)

    data = {
        "id": str(channel.id),
        "name": channel.name,
        "type": str(channel.type),
        "position": getattr(channel, "position", None),
        "category_id": (
            str(category.id)
            if category
            else None
        ),
        "category": (
            category.name
            if category
            else None
        ),
        "guild_id": str(guild.id),
        "guild_name": guild.name,
        "created_at": (
            channel.created_at.isoformat()
            if hasattr(channel, "created_at")
            else None
        )
    }

    if hasattr(channel, "topic"):
        data["topic"] = channel.topic

    if hasattr(channel, "slowmode_delay"):
        data["slowmode_delay"] = channel.slowmode_delay

    if hasattr(channel, "nsfw"):
        data["nsfw"] = channel.nsfw

    if hasattr(channel, "bitrate"):
        data["bitrate"] = channel.bitrate

    if hasattr(channel, "user_limit"):
        data["user_limit"] = channel.user_limit

    return jsonify({
        "success": True,
        "channel": data
    })
# =========================================================
# CHANNEL STATISTICS
# GET /api/servers/<guild_id>/channels/summary
# =========================================================

@api.get("/servers/<int:guild_id>/channels/summary")
@require_guild_access
@require_guild_manage
def channel_summary(guild_id):

    bot = discord_state.bot

    if bot is None:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(guild_id)

    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    channels = guild.channels

    text_channels = []
    voice_channels = []
    categories = []
    threads = []
    other = []

    for channel in channels:

        channel_type = str(channel.type).lower()

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

        "guild_id": str(guild.id),

        "guild_name": guild.name,

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
@require_guild_access
@require_guild_manage
def role_details(guild_id, role_id):

    bot = discord_state.bot

    if bot is None:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(guild_id)

    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    role = guild.get_role(role_id)

    if role is None:
        return jsonify({
            "success": False,
            "error": "Role not found."
        }), 404

    members_with_role = [
        member
        for member in guild.members
        if role in member.roles
    ]

    return jsonify({
        "success": True,

        "role": {
            "id": str(role.id),
            "name": role.name,
            "position": role.position,
            "color": str(role.color),
            "hoist": role.hoist,
            "mentionable": role.mentionable,
            "managed": role.managed,

            "member_count": len(
                members_with_role
            ),

            "permissions": [
                permission
                for permission, enabled
                in role.permissions
                if enabled
            ]
        }
    })
    
# =========================================================
# BOT HEALTH
# GET /api/health
# =========================================================

@api.get("/health")
@require_login
def bot_health():

    bot = discord_state.bot

    if bot is None:

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

    latency = round(
        bot.latency * 1000
    )

    if not discord_state.ready:

        status = "starting"

    elif latency < 200:

        status = "healthy"

    elif latency < 500:

        status = "degraded"

    else:

        status = "poor"

    return jsonify({

        "success": True,

        "health": {

            "status":
                status,

            "discord_connected":
                True,

            "discord_ready":
                discord_state.ready,

            "guild_count":
                len(bot.guilds),

            "latency_ms":
                latency,

            "user":
                (
                    {
                        "id": str(bot.user.id),
                        "name": str(bot.user)
                    }
                    if bot.user
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
            discord_state.ready,

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
@require_guild_access
@require_guild_manage
def server_statistics(guild_id):

    bot = discord_state.bot

    if bot is None:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    service = ServerService(bot)

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
@require_guild_access
@require_guild_manage
def server_activity(guild_id):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


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
            str(guild.id),

        "guild_name":
            guild.name,

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
@require_guild_access
@require_guild_manage
def server_activity_summary(
    guild_id
):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    guild = bot.get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

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
                str(guild.id),

            "name":
                guild.name
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
@require_guild_access
@require_guild_manage
def server_analytics(
    guild_id
):

    from collections import Counter
    from datetime import datetime, timezone, timedelta

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    # =====================================================
    # MEMBERS
    # =====================================================

    members = list(
        guild.members
    )

    human_count = 0
    bot_count = 0

    online_count = 0
    idle_count = 0
    dnd_count = 0
    offline_count = 0

    for member in members:

        if member.bot:

            bot_count += 1

        else:

            human_count += 1


        status = str(
            member.status
        )


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

    channels = list(
        guild.channels
    )

    text_channels = len(
        guild.text_channels
    )

    voice_channels = len(
        guild.voice_channels
    )

    categories = len(
        guild.categories
    )

    stage_channels = sum(
        1
        for channel in channels
        if str(
            channel.type
        ) == "stage_voice"
    )

    forum_channels = sum(
        1
        for channel in channels
        if str(
            channel.type
        ) == "forum"
    )


    # =====================================================
    # ROLES
    # =====================================================

    roles = list(
        guild.roles
    )

    managed_roles = sum(
        1
        for role in roles
        if role.managed
    )

    custom_roles = sum(
        1
        for role in roles
        if not role.managed
        and role.name != "@everyone"
    )

    administrator_roles = sum(
        1
        for role in roles
        if role.permissions.administrator
    )


    # =====================================================
    # EVENTS
    # =====================================================

    events = event_store.all_for_guild(
        guild.id
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
                guild.id
            ),

        "generated_at":
            now.isoformat(),

        "members": {

            "total":
                guild.member_count
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
