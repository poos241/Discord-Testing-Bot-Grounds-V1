from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_access, require_guild_manage, require_login


health_api = Blueprint(
    "health",
    __name__
)


def get_bot():

    return discord_state.get_bot()


def get_guild(guild_id):

    bot = get_bot()

    if bot is None:
        return None, "Discord bot is not connected."

    if not discord_state.ready:
        return None, "Discord bot is not ready."

    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:
        return None, "Discord server not found."

    return guild, None


@health_api.get(
    "/api/servers/<int:guild_id>/health"
)
@require_guild_access
@require_guild_manage
def server_health(guild_id):

    guild, error = get_guild(
        guild_id
    )

    if error:

        status = 503

        if error == "Discord server not found.":
            status = 404

        return jsonify({
            "success": False,
            "error": error
        }), status


    bot = get_bot()

    latency = None

    try:

        latency = round(
            bot.latency * 1000,
            2
        )

    except Exception:
        pass


    return jsonify({

        "success": True,

        "server": {

            "id":
                str(guild.id),

            "name":
                guild.name,

            "available":
                guild.available,

            "large":
                guild.large,

            "member_count":
                guild.member_count or 0,

            "cached_member_count":
                len(guild.members),

            "channel_count":
                len(guild.channels),

            "role_count":
                len(guild.roles),

            "category_count":
                len(guild.categories),

            "text_channel_count":
                len(guild.text_channels),

            "voice_channel_count":
                len(guild.voice_channels),

            "latency_ms":
                latency
        }

    })
