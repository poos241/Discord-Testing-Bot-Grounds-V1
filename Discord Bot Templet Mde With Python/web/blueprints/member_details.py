from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_access, require_guild_manage, require_login


member_details_api = Blueprint(
    "member_details",
    __name__
)


@member_details_api.get(
    "/api/servers/<int:guild_id>/members/<int:user_id>/details"
)
@require_guild_access
@require_guild_manage
def member_details(
    guild_id,
    user_id
):

    bot = discord_state.bot

    if bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    member = guild.get_member(
        int(user_id)
    )

    if member is None:

        return jsonify({
            "success": False,
            "error": "Member not found."
        }), 404


    roles = []


    for role in member.roles:

        if role.name == "@everyone":
            continue


        roles.append({

            "id":
                str(role.id),

            "name":
                role.name,

            "position":
                role.position,

            "color":
                str(role.color),

            "managed":
                role.managed
        })


    permissions = []


    for permission, enabled in member.guild_permissions:

        if enabled:

            permissions.append(
                permission
            )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "member": {

            "id":
                str(member.id),

            "username":
                member.name,

            "display_name":
                member.display_name,

            "nickname":
                member.nick,

            "bot":
                member.bot,

            "system":
                member.system,

            "avatar":
                (
                    str(member.display_avatar.url)
                    if member.display_avatar
                    else None
                ),

            "created_at":
                member.created_at.isoformat(),

            "joined_at":
                (
                    member.joined_at.isoformat()
                    if member.joined_at
                    else None
                ),

            "status":
                str(member.status),

            "desktop_status":
                str(member.desktop_status),

            "mobile_status":
                str(member.mobile_status),

            "web_status":
                str(member.web_status),

            "roles":
                roles,

            "role_count":
                len(roles),

            "top_role": {

                "id":
                    str(member.top_role.id),

                "name":
                    member.top_role.name,

                "position":
                    member.top_role.position,

                "color":
                    str(member.top_role.color)
            },

            "permissions":
                permissions,

            "permission_count":
                len(permissions),

            "administrator":
                member.guild_permissions.administrator,

            "manage_guild":
                member.guild_permissions.manage_guild,

            "manage_channels":
                member.guild_permissions.manage_channels,

            "manage_roles":
                member.guild_permissions.manage_roles,

            "manage_messages":
                member.guild_permissions.manage_messages,

            "kick_members":
                member.guild_permissions.kick_members,

            "ban_members":
                member.guild_permissions.ban_members,

            "moderate_members":
                member.guild_permissions.moderate_members,

            "manage_nicknames":
                member.guild_permissions.manage_nicknames,
        }

    })
