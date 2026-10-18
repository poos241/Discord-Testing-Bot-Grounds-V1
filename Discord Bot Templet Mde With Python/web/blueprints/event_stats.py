from collections import Counter

from flask import (
    Blueprint,
    jsonify
)

from web.services.discord_state import discord_state
from web.services.event_store import event_store
from web.security.decorators import require_guild_access, require_guild_manage, require_login


event_stats_api = Blueprint(
    "event_stats",
    __name__
)


@event_stats_api.get(
    "/api/servers/<int:guild_id>/event-stats"
)
@require_guild_access
def event_stats(
    guild_id
):

    bot = discord_state.get_bot()


    if bot is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected."

        }), 503


    if not discord_state.ready:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not ready."

        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found."

        }), 404


    events = event_store.for_guild(
        guild.id,
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
                guild.id
            ),

        "total_events":
            event_store.count_for_guild(
                guild.id
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
