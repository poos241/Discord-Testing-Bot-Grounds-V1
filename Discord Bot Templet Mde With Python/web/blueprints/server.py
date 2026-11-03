from flask import (
    Blueprint,
    jsonify,
)

from web.services import bridge

from web.services.permissions import (
    get_access_level,
    is_guild_owner,
)
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


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

    if not bridge.bot_is_ready():

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


    # =====================================================
    # BUILD SERVER LIST
    # =====================================================
    # Show every server the user is a member of, tagged with
    # their access level (viewer / moderator / admin).

    result = []

    try:
        bot_guilds = bridge.get_guilds() or []
    except Exception:
        bot_guilds = []

    for guild in bot_guilds:

        guild_id = str(
            guild.get("id")
        )


        level = get_access_level(
            guild_id
        )


        # User is not a member of this server.
        if level is None:

            continue


        try:

            result.append({

                "id":
                    guild_id,

                "name":
                    guild.get("name"),

                "member_count":
                    int(guild.get("member_count") or 0),

                "channel_count":
                    int(guild.get("channel_count") or 0),

                "role_count":
                    int(guild.get("role_count") or 0),

                "category_count":
                    int(guild.get("category_count") or 0),

                "icon":
                    guild.get("icon"),

                "banner":
                    guild.get("banner"),

                "owner_id":
                    (
                        str(
                            guild.get("owner_id")
                        )
                        if guild.get("owner_id")
                        else None
                    ),

                "access_level":
                    level,

                "can_manage":
                    level
                    in (
                        "moderator",
                        "admin",
                    ),

                "is_admin":
                    level
                    == "admin",

                "owner":
                    bool(
                        is_guild_owner(
                            guild_id
                        )
                    ),

            })

        except Exception as exc:

            print(
                "[Servers API] Failed to serialize "
                f"{guild.get('id')}: {exc}"
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
@require_guild_moderator
def get_server_channels(
    guild_id
):

    if not bridge.bot_is_ready():

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected.",

        }), 503


    guild = bridge.get_guild(
        int(guild_id)
    )


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found.",

        }), 404


    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except Exception:
        bridge_channels = []

    channels = []


    for channel in bridge_channels:

        channels.append({

            "id":
                str(
                    channel.get("id")
                ),

            "name":
                channel.get("name"),

            "type":
                str(
                    channel.get("type")
                ),

            "position":
                channel.get("position", 0),

            "category_id":
                channel.get("category_id"),

            "category":
                channel.get("category"),

            "nsfw":
                bool(
                    channel.get(
                        "nsfw",
                        False
                    )
                ),

            "created_at":
                channel.get("created_at"),

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
