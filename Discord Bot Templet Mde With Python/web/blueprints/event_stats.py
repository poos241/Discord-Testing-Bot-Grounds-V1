from collections import Counter

from flask import (
    Blueprint,
    jsonify
)

from web.services import bridge
from web.services.event_store import event_store
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


event_stats_api = Blueprint(
    "event_stats",
    __name__
)


@event_stats_api.get(
    "/api/servers/<int:guild_id>/event-stats"
)
@require_guild_moderator
def event_stats(
    guild_id
):

    if not bridge.bot_is_ready():

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected."

        }), 503


    guild = None
    try:
        guild = bridge.get_guild(int(guild_id))
    except Exception:
        guild = None


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found."

        }), 404


    events = event_store.for_guild(
        guild.get("id"),
        limit=5000
    )


    categories = Counter(

        str(
            event.get(
                "category"
            )
            or
            "unknown"
        )

        for event
        in events

    )


    event_types = Counter(

        str(

            event.get(
                "event_type"
            )

            or

            event.get(
                "event"
            )

            or

            event.get(
                "type"
            )

            or

            "unknown"

        )

        for event
        in events

    )


    return jsonify({

        "success":
            True,

        "guild_id":
            str(
                guild.get("id")
            ),

        "total_events":
            event_store.count_for_guild(
                guild.get("id")
            ),

        "categories":
            dict(
                categories
            ),

        "event_types":
            dict(
                event_types
            ),

        "top_events":
            [

                {
                    "event_type":
                        name,

                    "count":
                        count
                }

                for name,
                count
                in event_types.most_common(
                    10
                )

            ]

    })
