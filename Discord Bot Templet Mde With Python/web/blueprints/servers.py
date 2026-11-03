from flask import (
    Blueprint,
    jsonify,
    session,
)

from web.services import bridge

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

    # ---------------------------------------------------------
    # BOT CONNECTION
    # ---------------------------------------------------------

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
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

    try:
        bot_guilds = bridge.get_guilds() or []
    except Exception:
        bot_guilds = []

    for guild in bot_guilds:

        guild_id = str(
            guild.get("id")
        )

        access = manageable_map.get(
            guild_id
        )


        if not access:

            continue


        try:

            # NOTE: the old code forced the icon to 128px; the bridge
            # guild dict carries the full-size icon URL, which is what
            # the frontend gets now.
            icon_url = guild.get("icon")
            banner_url = guild.get("banner")
            owner_id = guild.get("owner_id")


            result.append({

                "id":
                    guild_id,

                "name":
                    guild.get("name"),

                "icon":
                    icon_url,

                "banner":
                    banner_url,

                "member_count":
                    int(guild.get("member_count") or 0),

                "channel_count":
                    int(guild.get("channel_count") or 0),

                "role_count":
                    int(guild.get("role_count") or 0),

                "category_count":
                    int(guild.get("category_count") or 0),

                "text_channel_count":
                    int(guild.get("text_channel_count") or 0),

                "voice_channel_count":
                    int(guild.get("voice_channel_count") or 0),

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
