from flask import Blueprint, jsonify

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


channels_api = Blueprint(
    "channels",
    __name__
)


def get_bot():
    """Kept for call-site compat (members.py used to import it).
    Always None now -- there is no live bot object in this process."""
    return None


def get_guild(guild_id):
    """Bridge guild dict, or None when the bot is down / not in it."""
    try:
        if not bridge.bot_is_ready():
            print("[ChannelsAPI] Discord bot is not ready.")
            return None
        return bridge.get_guild(int(guild_id))
    except Exception:
        print("[ChannelsAPI] Discord bot is not connected.")
        return None


def _bot_error():
    """(response, status) when the bot is down/not ready, else None."""
    if not bridge.bot_is_ready():
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "channels": []
        }), 503
    return None


# ============================================================
# GET SERVER CHANNELS
#
# GET /api/servers/<guild_id>/channels
# ============================================================

@channels_api.get(
    "/api/servers/<int:guild_id>/channels"
)
@require_guild_moderator
def get_server_channels(guild_id):

    denied = _bot_error()
    if denied:
        return denied

    guild = get_guild(guild_id)

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id),
            "channels": []
        }), 404

    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "channels": []
        }), 503

    channels = [
        {
            "id": str(channel.get("id")),
            "name": channel.get("name"),
            "type": channel.get("type"),
            "position": channel.get("position", 0),
            "category_id": channel.get("category_id"),
            "category": channel.get("category"),
            "created_at": channel.get("created_at"),
        }
        for channel in bridge_channels
    ]

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

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
@require_guild_moderator
def channel_summary(guild_id):

    if not bridge.bot_is_ready():

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected."

        }), 503


    guild = get_guild(
        guild_id
    )


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found."

        }), 404

    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    def _count(*types):
        return sum(
            1
            for channel in bridge_channels
            if (channel.get("type") or "") in types
        )

    text_channels = _count("text")
    voice_channels = _count("voice")
    categories = _count("category")
    stage_channels = _count("stage_voice")
    forum_channels = _count("forum")

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "total":
            len(bridge_channels),

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
