from flask import Blueprint, jsonify

from web.services import bridge
from web.services.member_service import MemberService
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


server_overview_api = Blueprint(
    "server_overview",
    __name__
)


@server_overview_api.get(
    "/api/servers/<int:guild_id>/quick-overview"
)
@require_guild_moderator
def quick_overview(guild_id):

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    guild = bridge.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    online_members = 0
    idle_members = 0
    dnd_members = 0
    offline_members = 0
    bot_members = 0


    for member in MemberService().get_members(guild_id):

        if member.get("bot"):

            bot_members += 1


        status = str(
            member.get("status") or "offline"
        ).lower()


        if status == "online":

            online_members += 1

        elif status == "idle":

            idle_members += 1

        elif status == "dnd":

            dnd_members += 1

        else:

            offline_members += 1


    return jsonify({

        "success": True,

        "server": {

            "id":
                str(guild.get("id")),

            "name":
                guild.get("name"),

            "icon":
                guild.get("icon"),

            "banner":
                guild.get("banner"),

            "owner_id":
                (
                    str(guild.get("owner_id"))
                    if guild.get("owner_id")
                    else None
                ),

            "member_count":
                int(guild.get("member_count") or 0),

            "channels":
                int(guild.get("channel_count") or 0),

            "roles":
                int(guild.get("role_count") or 0),

            "categories":
                int(guild.get("category_count") or 0),

            "members": {

                "online":
                    online_members,

                "idle":
                    idle_members,

                "dnd":
                    dnd_members,

                "offline":
                    offline_members,

                "bots":
                    bot_members
            }
        },

        "bot": {

            "ready":
                bridge.bot_is_ready(),

            "latency_ms":
                round(
                    float((bridge.status() or {}).get("latency_ms") or 0),
                    2
                )
        }

    })
