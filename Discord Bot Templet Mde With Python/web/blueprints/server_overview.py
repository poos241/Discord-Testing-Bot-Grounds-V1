from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_manage, require_login, require_guild_member


server_overview_api = Blueprint(
    "server_overview",
    __name__
)


@server_overview_api.get(
    "/api/servers/<int:guild_id>/quick-overview"
)
@require_guild_member
def quick_overview(guild_id):

    bot = discord_state.get_bot()

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


    online_members = 0
    idle_members = 0
    dnd_members = 0
    offline_members = 0
    bot_members = 0


    for member in guild.members:

        if member.bot:

            bot_members += 1


        status = str(
            member.status
        )


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
                str(guild.id),

            "name":
                guild.name,

            "icon":
                (
                    str(guild.icon.url)
                    if guild.icon
                    else None
                ),

            "banner":
                (
                    str(guild.banner.url)
                    if guild.banner
                    else None
                ),

            "owner_id":
                (
                    str(guild.owner_id)
                    if guild.owner_id
                    else None
                ),

            "member_count":
                guild.member_count or 0,

            "channels":
                len(guild.channels),

            "roles":
                len(guild.roles),

            "categories":
                len(guild.categories),

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
                discord_state.ready,

            "latency_ms":
                round(
                    bot.latency * 1000,
                    2
                )
        }

    })
