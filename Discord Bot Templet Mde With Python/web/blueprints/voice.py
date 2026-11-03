from flask import Blueprint, jsonify

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.security.decorators import require_guild_moderator


voice_api = Blueprint(
    "voice",
    __name__
)


def get_bot():
    """Kept for call-site compat. Always None now -- there is no live
    bot object in this process."""
    return None


def get_guild(guild_id):
    if not bridge.bot_is_ready():
        print("[VoiceAPI] Discord bot is not connected.")
        return None
    try:
        return bridge.get_guild(int(guild_id))
    except Exception:
        print("[VoiceAPI] Discord bot is not connected.")
        return None


def _member_voice_info(member):
    """One member's voice presence, from a bridge member dict.

    DEGRADATION: the bridge /voice endpoint lists occupants but
    exposes no per-member voice states, so muted/deafened/streaming/
    video always come back False. The keys stay so the frontend
    shape is unchanged.
    """
    return {
        "id": str(member.get("id")),
        "name": member.get("username"),
        "display_name": member.get("display_name"),
        "avatar_url": member.get("avatar"),
        "bot": bool(member.get("bot", False)),
        "muted": False,
        "deafened": False,
        "streaming": False,
        "video": False,
    }


# ============================================================
# GET LIVE VOICE CHANNELS
#
# GET /api/servers/<guild_id>/voice
#
# Live data only: this reads the bot's in-memory voice state
# (voice_states intent), so it is as current as the bot's cache.
# No database table is involved, so there is nothing stale to
# reconcile and no migration to run.
# ============================================================

@voice_api.get(
    "/api/servers/<int:guild_id>/voice"
)
@require_guild_moderator
def get_live_voice(guild_id):

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "channels": []
        }), 503

    guild = get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id),
            "channels": []
        }), 404

    channels = []
    total_in_voice = 0

    # Full channel list (voice + stage, including empty ones) merged
    # with the bridge /voice occupants. The bridge /voice endpoint
    # only returns occupied voice channels, so the merge is what
    # keeps empty channels visible like before.
    try:
        all_channels = bridge.get_channels(int(guild_id)) or []
    except BridgeUnavailable:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
            "channels": []
        }), 503
    try:
        voice_state = bridge.get_voice(int(guild_id)) or []
    except Exception:
        voice_state = []
    occupants = {
        str(entry.get("channel_id")): entry.get("members") or []
        for entry in voice_state
    }

    voice_channels = sorted(
        [c for c in all_channels if (c.get("type") or "") == "voice"],
        key=lambda c: c.get("position") or 0,
    )
    stage_channels = sorted(
        [c for c in all_channels if (c.get("type") or "") == "stage_voice"],
        key=lambda c: c.get("position") or 0,
    )

    for channel in voice_channels + stage_channels:

        members = [
            _member_voice_info(member)
            for member in sorted(
                occupants.get(str(channel.get("id")), []),
                key=lambda m: (
                    m.get("display_name") or m.get("username") or ""
                ).lower()
            )
        ]

        total_in_voice += len(members)

        channels.append({

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

            "user_limit":
                channel.get("user_limit") or 0,

            "member_count":
                len(members),

            # Opens the channel in Discord (app or web). Selecting a
            # voice channel in Discord connects you to it, so this is
            # the join link: there is no URL that force-joins a VC.
            "join_url":
                "https://discord.com/channels/{}/{}".format(
                    guild.get("id"), channel.get("id")
                ),

            "members":
                members

        })

    occupied = len([
        channel
        for channel in channels
        if channel["member_count"] > 0
    ])

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "total_in_voice":
            total_in_voice,

        "voice_channel_count":
            len(voice_channels),

        "stage_channel_count":
            len(stage_channels),

        "occupied_channel_count":
            occupied,

        "count":
            len(channels),

        "channels":
            channels

    })
