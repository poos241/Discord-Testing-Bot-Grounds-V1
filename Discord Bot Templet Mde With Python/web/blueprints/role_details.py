from flask import Blueprint, jsonify

from web.services.discord_state import discord_state

from web.blueprints.auth import (
    user_can_manage_guild
)
from web.security.decorators import require_guild_manage, require_login, require_guild_member

role_details_api = Blueprint(
    "role_details",
    __name__
)


@role_details_api.get(
    "/api/servers/<int:guild_id>/roles/<int:role_id>/details"
)
@require_guild_member
def role_details(
    guild_id,
    role_id
):

    bot = discord_state.get_bot()


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


    if not user_can_manage_guild(
        guild_id
    ):

        return jsonify({

            "success":
                False,

            "error":
                "You do not have permission to view this role."

        }), 403


    guild = bot.get_guild(
        int(guild_id)
    )


    role = guild.get_role(
        int(role_id)
    )

    if role is None:

        return jsonify({
            "success": False,
            "error": "Role not found."
        }), 404


    permissions = []


    for permission, enabled in role.permissions:

        if enabled:

            permissions.append(
                permission
            )


    members = []


    for member in guild.members:

        if role in member.roles:

            members.append({

                "id":
                    str(member.id),

                "username":
                    member.name,

                "display_name":
                    member.display_name,

                "bot":
                    member.bot
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "role": {

            "id":
                str(role.id),

            "name":
                role.name,

            "position":
                role.position,

            "color":
                str(role.color),

            "hoist":
                role.hoist,

            "managed":
                role.managed,

            "mentionable":
                role.mentionable,

            "created_at":
                role.created_at.isoformat(),

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
