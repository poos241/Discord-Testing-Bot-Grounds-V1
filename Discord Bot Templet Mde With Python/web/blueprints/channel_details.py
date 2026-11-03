from flask import Blueprint, jsonify

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


channel_details_api = Blueprint(
    "channel_details",
    __name__
)


def get_bot():
    """Kept for call-site compat. Always None now -- there is no live
    bot object in this process."""
    return None


def get_guild(guild_id):
    """Bridge guild dict, or None when the bot is down / not in it."""
    try:
        if not bridge.bot_is_ready():
            return None
        return bridge.get_guild(int(guild_id))
    except Exception:
        return None


@channel_details_api.get(
    "/api/servers/<int:guild_id>/channels/<int:channel_id>/details"
)
@require_guild_moderator
def channel_details(
    guild_id,
    channel_id
):

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    guild = get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    try:
        bridge_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503
    channel = None
    for candidate in bridge_channels:
        if str(candidate.get("id")) == str(channel_id):
            channel = candidate
            break

    if channel is None:

        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404


    data = {

        "id":
            str(channel.get("id")),

        "name":
            channel.get("name"),

        "type":
            str(channel.get("type")),

        "position":
            channel.get("position"),

        "category_id":
            channel.get("category_id"),

        "category":
            channel.get("category"),

        "topic":
            channel.get("topic"),

        "nsfw":
            bool(channel.get("nsfw", False)),

        "slowmode_delay":
            channel.get("slowmode_delay", 0),

        "created_at":
            channel.get("created_at"),
    }


    # -----------------------------------------------------
    # PERMISSIONS
    # -----------------------------------------------------
    # Channel permission overwrites are NOT exposed by the bridge
    # (no endpoint for them), so this degrades to an empty list
    # instead of crashing. The key stays so the frontend shape is
    # unchanged. A bridge overwrites endpoint is the follow-up if
    # the panel needs them back.

    data["permissions"] = []


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "channel":
            data
    })
