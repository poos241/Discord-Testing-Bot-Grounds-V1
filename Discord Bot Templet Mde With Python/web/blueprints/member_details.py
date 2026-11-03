from flask import Blueprint, jsonify

import discord

from web.services import bridge
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


member_details_api = Blueprint(
    "member_details",
    __name__
)


@member_details_api.get(
    "/api/servers/<int:guild_id>/members/<int:user_id>/details"
)
@require_guild_moderator
def member_details(
    guild_id,
    user_id
):

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


    member = bridge.get_member(
        int(guild_id),
        int(user_id)
    )

    if member is None:

        return jsonify({
            "success": False,
            "error": "Member not found."
        }), 404


    roles = []


    for role in (member.get("roles") or []):

        if role.get("name") == "@everyone":
            continue


        roles.append({

            "id":
                str(role.get("id")),

            "name":
                role.get("name"),

            "position":
                role.get("position"),

            "color":
                role.get("color"),

            "managed":
                role.get("managed")
        })


    guild_permissions = discord.Permissions(
        int(member.get("guild_permissions") or 0)
    )

    permissions = [
        name
        for name, enabled in guild_permissions
        if enabled
    ]


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "member": {

            "id":
                str(member.get("id")),

            "username":
                member.get("username"),

            "display_name":
                member.get("display_name"),

            "nickname":
                member.get("nickname"),

            "bot":
                member.get("bot"),

            # The bridge exposes no "system" flag; always False.
            "system":
                False,

            "avatar":
                member.get("avatar"),

            "created_at":
                member.get("created_at"),

            "joined_at":
                member.get("joined_at"),

            "status":
                str(member.get("status") or "offline"),

            # The bridge exposes only an overall status, not per-client
            # statuses, so these degrade to the overall status.
            "desktop_status":
                str(member.get("status") or "offline"),

            "mobile_status":
                str(member.get("status") or "offline"),

            "web_status":
                str(member.get("status") or "offline"),

            "roles":
                roles,

            "role_count":
                len(roles),

            "top_role": (
                {
                    "id": str((member.get("top_role") or {}).get("id")),
                    "name": (member.get("top_role") or {}).get("name"),
                    "position": (member.get("top_role") or {}).get("position"),
                    "color": (member.get("top_role") or {}).get("color"),
                }
                if member.get("top_role")
                else None
            ),

            "permissions":
                permissions,

            "permission_count":
                len(permissions),

            "administrator":
                guild_permissions.administrator,

            "manage_guild":
                guild_permissions.manage_guild,

            "manage_channels":
                guild_permissions.manage_channels,

            "manage_roles":
                guild_permissions.manage_roles,

            "manage_messages":
                guild_permissions.manage_messages,

            "kick_members":
                guild_permissions.kick_members,

            "ban_members":
                guild_permissions.ban_members,

            "moderate_members":
                guild_permissions.moderate_members,

            "manage_nicknames":
                guild_permissions.manage_nicknames,
        }

    })
