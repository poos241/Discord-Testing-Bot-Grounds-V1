from flask import (
    Blueprint,
    jsonify,
    session,
)

from web.services.discord_state import discord_state

from web.blueprints.auth import (
    get_manageable_guilds,
)
from web.security.decorators import require_guild_manage, require_login


servers_api = Blueprint(
    "servers",
    __name__,
)


# =========================================================
# DISCORD SERVERS
# =========================================================

@servers_api.get("/servers")
@require_login
def servers():

    bot = discord_state.bot

    # ---------------------------------------------------------
    # BOT CONNECTION
    # ---------------------------------------------------------

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "servers": [],
            "count": 0
        }), 503


    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready.",
            "servers": [],
            "count": 0
        }), 503


    # ---------------------------------------------------------
    # GET SERVERS USER CAN MANAGE
    # ---------------------------------------------------------

    try:

        manageable_guilds = (
            get_manageable_guilds()
        )

    except Exception as exc:

        print(
            f"[Servers API] Failed to get manageable "
            f"guilds: {exc}"
        )

        return jsonify({
            "success": False,
            "error": "Unable to determine server permissions.",
            "servers": [],
            "count": 0
        }), 500


    manageable_map = {

        str(guild["id"]):
            guild

        for guild in manageable_guilds

        if guild.get("id") is not None

    }


    result = []


    # ---------------------------------------------------------
    # ONLY SERVERS WHERE:
    #
    # 1. BOT IS INSTALLED
    # 2. USER CAN MANAGE SERVER
    # ---------------------------------------------------------

    for guild in bot.guilds:

        guild_id = str(
            guild.id
        )

        access = manageable_map.get(
            guild_id
        )


        if not access:

            continue


        try:

            icon_url = None

            if guild.icon:

                icon_url = str(
                    guild.icon.with_size(128).url
                )


            banner_url = None

            if guild.banner:

                banner_url = str(
                    guild.banner.url
                )


            owner_id = getattr(
                guild,
                "owner_id",
                None
            )


            result.append({

                "id":
                    guild_id,

                "name":
                    guild.name,

                "icon":
                    icon_url,

                "banner":
                    banner_url,

                "member_count":
                    int(
                        guild.member_count
                        or len(guild.members)
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

                "text_channel_count":
                    len(
                        guild.text_channels
                    ),

                "voice_channel_count":
                    len(
                        guild.voice_channels
                    ),

                "owner_id":
                    (
                        str(owner_id)
                        if owner_id is not None
                        else None
                    ),

                "owner":
                    bool(
                        access.get(
                            "owner",
                            False
                        )
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

                "created_at":
                    (
                        guild.created_at.isoformat()
                        if guild.created_at
                        else None
                    ),

            })


        except Exception as exc:

            print(
                "[Servers API] Failed to serialize "
                f"guild {guild_id}: {exc}"
            )


    # ---------------------------------------------------------
    # SORT
    # ---------------------------------------------------------

    result.sort(
        key=lambda server:
            (
                server.get("name")
                or ""
            ).lower()
    )


    # ---------------------------------------------------------
    # RESPONSE
    # ---------------------------------------------------------

    return jsonify({

        "success":
            True,

        "count":
            len(result),

        "servers":
            result

    })
