from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_moderator


voice_api = Blueprint(
    "voice",
    __name__
)


def get_bot():
    return discord_state.bot


def get_guild(guild_id):
    bot = get_bot()

    if bot is None:
        print("[VoiceAPI] Discord bot is not connected.")
        return None

    if not discord_state.ready:
        print("[VoiceAPI] Discord bot is not ready.")
        return None

    return bot.get_guild(int(guild_id))


def _member_voice_info(member):
    """One member's live voice state, from the bot's voice_states cache.

    ``member.voice`` is None when the member is not in a voice channel;
    callers only pass members taken from a channel's member list, so it
    is normally set, but guard anyway.
    """
    voice = getattr(member, "voice", None)

    muted = False
    deafened = False
    streaming = False
    video = False

    if voice is not None:
        muted = bool(
            getattr(voice, "self_mute", False)
            or getattr(voice, "mute", False)
        )
        deafened = bool(
            getattr(voice, "self_deaf", False)
            or getattr(voice, "deaf", False)
        )
        streaming = bool(getattr(voice, "self_stream", False))
        video = bool(getattr(voice, "self_video", False))

    avatar = None
    try:
        avatar = str(member.display_avatar.url)
    except Exception:
        avatar = None

    return {
        "id": str(member.id),
        "name": member.name,
        "display_name": member.display_name,
        "avatar_url": avatar,
        "bot": bool(getattr(member, "bot", False)),
        "muted": muted,
        "deafened": deafened,
        "streaming": streaming,
        "video": video,
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
    total_in_voice = 0

    # Voice channels first (by position), then stage channels.
    # channel.members is populated from voice_states, so a member
    # listed here is in this channel right now.
    voice_channels = list(guild.voice_channels)
    stage_channels = [
        channel
        for channel in guild.channels
        if str(channel.type) == "stage_voice"
    ]

    for channel in voice_channels + stage_channels:

        category = getattr(
            channel,
            "category",
            None
        )

        members = [
            _member_voice_info(member)
            for member in sorted(
                channel.members,
                key=lambda m: (m.display_name or m.name).lower()
            )
        ]

        total_in_voice += len(members)

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

            "user_limit":
                getattr(channel, "user_limit", 0) or 0,

            "member_count":
                len(members),

            # Opens the channel in Discord (app or web). Selecting a
            # voice channel in Discord connects you to it, so this is
            # the join link: there is no URL that force-joins a VC.
            "join_url":
                "https://discord.com/channels/{}/{}".format(
                    guild.id, channel.id
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
            str(guild.id),

        "guild_name":
            guild.name,

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
