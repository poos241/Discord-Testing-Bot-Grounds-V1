from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_access, require_guild_manage, require_login


channels_api = Blueprint(
    "channels",
    __name__
)


def get_bot():
    return discord_state.bot


def get_guild(guild_id):
    bot = get_bot()

    if bot is None:
        print("[ChannelsAPI] Discord bot is not connected.")
        return None

    if not discord_state.ready:
        print("[ChannelsAPI] Discord bot is not ready.")
        return None

    return bot.get_guild(int(guild_id))


# ============================================================
# GET SERVER CHANNELS
#
# GET /api/servers/<guild_id>/channels
# ============================================================

@channels_api.get(
    "/api/servers/<int:guild_id>/channels"
)
@require_guild_access
@require_guild_manage
def get_server_channels(guild_id):

    bot = get_bot()

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "channels": []
        }), 503


    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready.",
            "channels": []
        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )


    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id),
            "channels": []
        }), 404


    channels = []


    for channel in guild.channels:

        category = getattr(
            channel,
            "category",
            None
        )


        channels.append({

            "id":
                str(channel.id),

            "name":
                channel.name,

            "type":
                str(channel.type),

            "position":
                channel.position,

            "category_id":
                (
                    str(category.id)
                    if category
                    else None
                ),

            "category":
                (
                    category.name
                    if category
                    else None
                ),

            "created_at":
                (
                    channel.created_at.isoformat()
                    if getattr(
                        channel,
                        "created_at",
                        None
                    )
                    else None
                )

        })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "count":
            len(channels),

        "channels":
            channels

    })
    
    
# ============================================================
# GET CHANNEL SUMMARY
#
# GET /api/servers/<guild_id>/channels/summary
# ============================================================

@channels_api.get(
    "/api/servers/<int:guild_id>/channels/summary"
)
@require_guild_access
@require_guild_manage
def channel_summary(guild_id):

    bot = get_bot()


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


    text_channels = len(
        guild.text_channels
    )

    voice_channels = len(
        guild.voice_channels
    )

    categories = len(
        guild.categories
    )

    stage_channels = len([
        channel
        for channel in guild.channels
        if str(channel.type) == "stage_voice"
    ])

    forum_channels = len([
        channel
        for channel in guild.channels
        if str(channel.type) == "forum"
    ])


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "total":
            len(guild.channels),

        "text":
            text_channels,

        "voice":
            voice_channels,

        "categories":
            categories,

        "stage":
            stage_channels,

        "forum":
            forum_channels

    })
