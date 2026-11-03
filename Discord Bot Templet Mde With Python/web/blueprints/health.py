from flask import Blueprint, jsonify

from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.services.member_service import MemberService
from web.security.decorators import require_guild_access, require_guild_manage, require_login


health_api = Blueprint(
    "health",
    __name__
)


def get_bot():
    """Kept for call-site compat. Always None now -- there is no live
    bot object in this process."""
    return None


def get_guild(guild_id):

    if not bridge.bot_is_ready():
        return None, "Discord bot is not connected."

    guild = None
    try:
        guild = bridge.get_guild(int(guild_id))
    except Exception:
        guild = None

    if guild is None:
        return None, "Discord server not found."

    return guild, None


@health_api.get(
    "/api/servers/<int:guild_id>/health"
)
@require_guild_access
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


    latency = None

    try:
        latency = round(
            float(bridge.status().get("latency_ms") or 0),
            2
        )
    except Exception:
        pass


    return jsonify({

        "success": True,

        "server": {

            "id":
                str(guild.get("id")),

            "name":
                guild.get("name"),

            "available":
                guild.get("available", True),

            "large":
                (int(guild.get("member_count") or 0) > 250),

            "member_count":
                int(guild.get("member_count") or 0),

            "cached_member_count":
                len(MemberService().get_members(guild_id)),

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

            "latency_ms":
                latency
        }

    })
