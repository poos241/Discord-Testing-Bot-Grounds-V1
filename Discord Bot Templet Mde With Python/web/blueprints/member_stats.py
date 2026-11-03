from flask import Blueprint, jsonify

from web.services import bridge
from web.services.member_service import MemberService
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


member_stats_api = Blueprint(
    "member_stats",
    __name__
)


@member_stats_api.get(
    "/api/servers/<int:guild_id>/members/stats"
)
@require_guild_moderator
def member_stats(guild_id):

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


    members = MemberService().get_members(guild_id)


    bots = [
        member
        for member in members
        if member.get("bot")
    ]


    humans = [
        member
        for member in members
        if not member.get("bot")
    ]


    # NOTE: the old code compared a discord Status enum to the string
    # "offline" (always unequal), so the old online count was really
    # the total. The bridge status is a plain string, so this now
    # counts genuinely-online members.
    online = [
        member
        for member in members
        if str(member.get("status") or "offline").lower() not in ("offline", "invisible")
    ]


    administrators = []

    for member in members:

        if int(member.get("guild_permissions") or 0) & 0x8:

            administrators.append(
                member
            )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

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
