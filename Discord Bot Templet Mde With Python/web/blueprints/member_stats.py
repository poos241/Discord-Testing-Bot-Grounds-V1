from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_access, require_guild_manage, require_login


member_stats_api = Blueprint(
    "member_stats",
    __name__
)


@member_stats_api.get(
    "/api/servers/<int:guild_id>/members/stats"
)
@require_guild_access
@require_guild_manage
def member_stats(guild_id):

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


    bots = [
        member
        for member in members
        if member.bot
    ]


    humans = [
        member
        for member in members
        if not member.bot
    ]


    online = [
        member
        for member in members
        if member.status != "offline"
    ]


    administrators = []

    for member in members:

        if member.guild_permissions.administrator:

            administrators.append(
                member
            )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "total":
            len(members),

        "humans":
            len(humans),

        "bots":
            len(bots),

        "online":
            len(online),

        "administrators":
            len(administrators)

    })
