from flask import (
    Blueprint,
    jsonify,
)

from web.services.discord_state import discord_state

from web.blueprints.auth import (
    get_manageable_guilds,
)
from web.security.decorators import require_guild_access, require_guild_manage, require_login


servers_api = Blueprint(
    "servers",
    __name__,
    url_prefix="/api",
)


# =========================================================
# SERVERS
# =========================================================

@servers_api.get(
    "/servers"
)
@require_login
def servers():

    bot = discord_state.bot

    if bot is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected.",

            "servers":
                [],

            "count":
                0,

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

            "servers":
                [],

            "count":
                0,

        }), 503


    # =====================================================
    # USER PERMISSIONS
    # =====================================================

    try:

        manageable_guilds = (
            get_manageable_guilds()
        )

    except Exception as exc:

        print(
            "[Servers API] "
            f"Permission lookup failed: {exc}"
        )

        return jsonify({

            "success":
                False,

            "error":
                "Unable to determine "
                "server permissions.",

            "servers":
                [],

            "count":
                0,

        }), 500


    manageable_map = {

        str(
            guild.get("id")
        ):
            guild

        for guild
        in manageable_guilds

        if guild.get("id") is not None

    }


    # =====================================================
    # BUILD SERVER LIST
    # =====================================================

    result = []


    for guild in bot.guilds:

        guild_id = str(
            guild.id
        )


        access = (
            manageable_map.get(
                guild_id
            )
        )


        # User cannot manage this server.
        if access is None:

            continue


        try:

            result.append({

                "id":
                    guild_id,

                "name":
                    guild.name,

                "member_count":
                    int(
                        guild.member_count
                        or len(
                            guild.members
                        )
                        or 0
                    ),

                "channel_count":
                    len(
                        guild.channels
                    ),

                "role_count":
                    len(
                        guild.roles
                    ),

                "category_count":
                    len(
                        guild.categories
                    ),

                "icon":
                    (
                        str(
                            guild.icon.url
                        )
                        if guild.icon
                        else None
                    ),

                "banner":
                    (
                        str(
                            guild.banner.url
                        )
                        if guild.banner
                        else None
                    ),

                "owner_id":
                    (
                        str(
                            guild.owner_id
                        )
                        if guild.owner_id
                        else None
                    ),

                "can_manage":
                    bool(
                        access.get(
                            "can_manage",
                            False
                        )
                    ),

                "is_admin":
                    bool(
                        access.get(
                            "is_admin",
                            False
                        )
                    ),

                "owner":
                    bool(
                        access.get(
                            "owner",
                            False
                        )
                    ),

            })

        except Exception as exc:

            print(
                "[Servers API] Failed to serialize "
                f"{guild.id}: {exc}"
            )


    result.sort(
        key=lambda server:
            server["name"].casefold()
    )


    return jsonify({

        "success":
            True,

        "count":
            len(result),

        "servers":
            result,

    })


# =========================================================
# SERVER CHANNELS
# =========================================================

@servers_api.get(
    "/servers/<int:guild_id>/channels"
)
@require_guild_access
def get_server_channels(
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


    channels = []


    for channel in guild.channels:

        channels.append({

            "id":
                str(
                    channel.id
                ),

            "name":
                channel.name,

            "type":
                str(
                    channel.type
                ),

            "position":
                channel.position,

            "category_id":
                (
                    str(
                        channel.category_id
                    )
                    if channel.category_id
                    else None
                ),

            "category":
                (
                    channel.category.name
                    if channel.category
                    else None
                ),

            "nsfw":
                bool(
                    getattr(
                        channel,
                        "nsfw",
                        False
                    )
                ),

            "created_at":
                (
                    channel.created_at.isoformat()
                    if channel.created_at
                    else None
                ),

        })


    channels.sort(
        key=lambda channel:
            channel["position"]
    )


    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild_id),

        "count":
            len(channels),

        "channels":
            channels,

    })
