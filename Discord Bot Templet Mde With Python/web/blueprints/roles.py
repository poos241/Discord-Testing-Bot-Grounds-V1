from flask import (
    Blueprint,
    jsonify,
)

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


roles_api = Blueprint(
    "roles",
    __name__,
)


# =========================================================
# HELPERS
# =========================================================

def get_bot():

    return discord_state.bot


def get_guild(guild_id):

    bot = get_bot()

    if bot is None:
        return None

    if not discord_state.ready:
        return None

    try:

        return bot.get_guild(
            int(guild_id)
        )

    except (
        TypeError,
        ValueError
    ):

        return None


# =========================================================
# SERIALIZE ROLE
# =========================================================

def serialize_role(
    role,
    guild
):

    permissions = []

    for permission, enabled in role.permissions:

        if enabled:

            permissions.append(
                permission
            )


    member_count = 0

    for member in guild.members:

        if role in member.roles:

            member_count += 1


    return {

        "id":
            str(role.id),

        "name":
            role.name,

        "position":
            role.position,

        "color":
            str(role.color),

        "color_value":
            role.color.value,

        "hoist":
            role.hoist,

        "managed":
            role.managed,

        "mentionable":
            role.mentionable,

        "permissions":
            permissions,

        "permission_count":
            len(permissions),

        "member_count":
            member_count,

        "created_at":
            (
                role.created_at.isoformat()
                if role.created_at
                else None
            ),

    }


# =========================================================
# GET SERVER ROLES
#
# GET /api/servers/<guild_id>/roles
# =========================================================

@roles_api.get(
    "/api/servers/<int:guild_id>/roles"
)
@require_guild_moderator
def get_server_roles(
    guild_id
):

    bot = get_bot()


    if bot is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected.",

            "roles":
                []

        }), 503


    if not discord_state.ready:

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not ready.",

            "roles":
                []

        }), 503


    guild = get_guild(
        guild_id
    )


    if guild is None:

        return jsonify({

            "success":
                False,

            "error":
                "Discord server not found.",

            "roles":
                []

        }), 404


    roles = [

        serialize_role(
            role,
            guild
        )

        for role in guild.roles

    ]


    # Discord already returns roles
    # from lowest to highest position.
    #
    # Reverse them so the most powerful
    # roles appear first in the UI.

    roles.reverse()


    return jsonify({

        "success":
            True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "count":
            len(roles),

        "roles":
            roles

    })
