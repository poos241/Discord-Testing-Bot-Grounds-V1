from flask import Blueprint, jsonify, request

from web.services.event_store import event_store
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


events_api = Blueprint(
    "events",
    __name__,
    url_prefix="/api"
)


# =========================================================
# LIMIT
# =========================================================

def get_limit():

    try:

        limit = int(
            request.args.get(
                "limit",
                100
            )
        )

    except (
        TypeError,
        ValueError
    ):

        limit = 100

    return max(
        1,
        min(
            limit,
            500
        )
    )


# =========================================================
# ALL EVENTS
#
# /api/events
#
# Optional:
#
# ?guild_id=
# ?category=
# ?event_type=
# ?user_id=
# ?channel_id=
# ?limit=
#
# Examples:
#
# /api/events?limit=25
#
# /api/events?guild_id=557680433245061130
#
# /api/events?category=messages
#
# /api/events?event_type=message_deleted
# =========================================================

@events_api.get(
    "/events"
)
@require_login
def get_events():

    limit = get_limit()

    events = event_store.query(

        limit=limit,

        guild_id=request.args.get(
            "guild_id"
        ),

        category=request.args.get(
            "category"
        ),

        event_type=request.args.get(
            "event_type"
        ),

        user_id=request.args.get(
            "user_id"
        ),

        channel_id=request.args.get(
            "channel_id"
        )

    )

    return jsonify({

        "success":
            True,

        "count":
            len(events),

        "limit":
            limit,

        "filters": {

            "guild_id":
                request.args.get(
                    "guild_id"
                ),

            "category":
                request.args.get(
                    "category"
                ),

            "event_type":
                request.args.get(
                    "event_type"
                ),

            "user_id":
                request.args.get(
                    "user_id"
                ),

            "channel_id":
                request.args.get(
                    "channel_id"
                ),

        },

        "events":
            events

    })


# =========================================================
# SERVER EVENTS
#
# /api/servers/<guild_id>/events
# =========================================================

@events_api.get(
    "/servers/<int:guild_id>/events"
)
@require_guild_moderator
def get_server_events(
    guild_id
):

    limit = get_limit()

    events = event_store.for_guild(
        guild_id,
        limit
    )

    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild_id),

        "count":
            len(events),

        "events":
            events

    })


# =========================================================
# EVENT TYPE
#
# /api/events/type/message_deleted
# =========================================================

@events_api.get(
    "/events/type/<path:event_type>"
)
@require_login
def get_event_type(
    event_type
):

    limit = get_limit()

    events = event_store.by_type(
        event_type,
        limit
    )

    return jsonify({

        "success":
            True,

        "event_type":
            event_type,

        "count":
            len(events),

        "events":
            events

    })


# =========================================================
# EVENT CATEGORY
#
# /api/events/category/messages
# =========================================================

@events_api.get(
    "/events/category/<path:category>"
)
@require_login
def get_event_category(
    category
):

    limit = get_limit()

    events = event_store.by_category(
        category,
        limit
    )

    return jsonify({

        "success":
            True,

        "category":
            category,

        "count":
            len(events),

        "events":
            events

    })


# =========================================================
# USER EVENTS
#
# /api/events/user/<user_id>
# =========================================================

@events_api.get(
    "/events/user/<int:user_id>"
)
@require_login
def get_user_events(
    user_id
):

    limit = get_limit()

    events = event_store.for_user(
        user_id,
        limit
    )

    return jsonify({

        "success":
            True,

        "user_id":
            str(user_id),

        "count":
            len(events),

        "events":
            events

    })


# =========================================================
# CHANNEL EVENTS
#
# /api/events/channel/<channel_id>
# =========================================================

@events_api.get(
    "/events/channel/<int:channel_id>"
)
@require_login
def get_channel_events(
    channel_id
):

    limit = get_limit()

    events = event_store.for_channel(
        channel_id,
        limit
    )

    return jsonify({

        "success":
            True,

        "channel_id":
            str(channel_id),

        "count":
            len(events),

        "events":
            events

    })


# =========================================================
# EVENT STORE STATUS
#
# Useful for dashboard/debugging
#
# /api/events/status
# =========================================================

@events_api.get(
    "/events/status"
)
@require_login
def event_status():

    return jsonify({

        "success":
            True,

        "stored_events":
            event_store.count(),

        "max_events":
            5000

    })
    
    
    
# =========================================================
# EVENT SUMMARY
#
# /api/events/summary
#
# Optional:
#
# ?guild_id=123
# =========================================================

@events_api.get(
    "/events/summary"
)
@require_login
def event_summary():

    guild_id = request.args.get(
        "guild_id"
    )

    events = event_store.query(
        limit=500,
        guild_id=guild_id
    )

    categories = {}
    event_types = {}
    users = {}
    channels = {}

    for event in events:

        category = (
            event.get(
                "category"
            )
            or "other"
        )

        event_type = (
            event.get(
                "event_type"
            )
            or event.get(
                "type"
            )
            or "unknown"
        )

        user_id = event.get(
            "user_id"
        )

        channel_id = event.get(
            "channel_id"
        )

        categories[category] = (
            categories.get(
                category,
                0
            ) + 1
        )

        event_types[event_type] = (
            event_types.get(
                event_type,
                0
            ) + 1
        )

        if user_id:

            users[str(user_id)] = (
                users.get(
                    str(user_id),
                    0
                ) + 1
            )

        if channel_id:

            channels[str(channel_id)] = (
                channels.get(
                    str(channel_id),
                    0
                ) + 1
            )

    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild_id)
            if guild_id
            else None,

        "total":
            len(events),

        "categories":
            categories,

        "event_types":
            event_types,

        "users":
            users,

        "channels":
            channels,

    })
