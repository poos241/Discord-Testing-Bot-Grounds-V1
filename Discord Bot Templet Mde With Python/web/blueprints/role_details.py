from flask import Blueprint, jsonify

import discord

from web.services import bridge
from web.services.member_service import MemberService

from web.blueprints.auth import (
    user_can_manage_guild
)
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator

role_details_api = Blueprint(
    "role_details",
    __name__
)


@role_details_api.get(
    "/api/servers/<int:guild_id>/roles/<int:role_id>/details"
)
@require_guild_moderator
def role_details(
    guild_id,
    role_id
):

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    if not user_can_manage_guild(
        guild_id
    ):

        return jsonify({

            "success":
                False,

            "error":
                "You do not have permission to view this role."

        }), 403


    guild = bridge.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    role = None
    for candidate in (bridge.get_roles(int(guild_id)) or []):
        if str(candidate.get("id")) == str(role_id):
            role = candidate
            break

    if role is None:

        return jsonify({
            "success": False,
            "error": "Role not found."
        }), 404


    role_perms = discord.Permissions(
        int(role.get("permissions") or 0)
    )

    permissions = [
        name
        for name, enabled in role_perms
        if enabled
    ]


    members = []

    for member in MemberService().get_members(guild_id):

        if any(
            str(r.get("id")) == str(role_id)
            for r in (member.get("roles") or [])
        ):

            members.append({

                "id":
                    str(member.get("id")),

                "username":
                    member.get("username"),

                "display_name":
                    member.get("display_name"),

                "bot":
                    member.get("bot")
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "role": {

            "id":
                str(role.get("id")),

            "name":
                role.get("name"),

            "position":
                role.get("position"),

            "color":
                role.get("color"),

            "hoist":
                role.get("hoist"),

            "managed":
                role.get("managed"),

            "mentionable":
                role.get("mentionable"),

            "created_at":
                discord.utils.snowflake_time(
                    int(role.get("id"))
                ).isoformat(),

            "permissions":
                permissions,

            "permission_count":
                len(permissions),

            "member_count":
                len(members),

            "members":
                members[:100]
        }

    })
