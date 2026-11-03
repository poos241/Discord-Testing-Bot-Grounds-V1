from flask import (
    Blueprint,
    jsonify,
)

import discord

from web.services import bridge
from web.services.member_service import MemberService
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


roles_api = Blueprint(
    "roles",
    __name__,
)


# =========================================================
# HELPERS
# =========================================================

def get_bot():
    """Kept for call-site compat. Always None now -- there is no live
    bot object in this process."""
    return None


def get_guild(guild_id):

    if not bridge.bot_is_ready():
        return None

    try:

        return bridge.get_guild(
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

def _role_color(role):
    """(color_str, color_value) from a bridge role dict.

    The real bridge sends color as a "#rrggbb" string; the harness
    fake (and any int source) may send an int instead."""
    raw = role.get("color")
    if isinstance(raw, int):
        return ("#%06x" % (raw & 0xFFFFFF)), raw
    if isinstance(raw, str) and raw:
        try:
            return raw, int(raw.lstrip("#"), 16)
        except ValueError:
            return raw, 0
    return "#000000", 0


def serialize_role(
    role,
    member_role_ids
):

    role_perms = discord.Permissions(
        int(role.get("permissions") or 0)
    )

    permissions = [
        name
        for name, enabled in role_perms
        if enabled
    ]

    color, color_value = _role_color(role)

    role_id = str(role.get("id"))
    member_count = sum(
        1
        for ids in member_role_ids
        if role_id in ids
    )

    created = None
    try:
        created = discord.utils.snowflake_time(
            int(role.get("id"))
        ).isoformat()
    except Exception:
        created = None

    return {

        "id":
            role_id,

        "name":
            role.get("name"),

        "position":
            role.get("position"),

        "color":
            color,

        "color_value":
            color_value,

        "hoist":
            role.get("hoist"),

        "managed":
            role.get("managed"),

        "mentionable":
            role.get("mentionable"),

        "permissions":
            permissions,

        "permission_count":
            len(permissions),

        "member_count":
            member_count,

        "created_at":
            created,

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

    if not bridge.bot_is_ready():

        return jsonify({

            "success":
                False,

            "error":
                "Discord bot is not connected.",

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

    bridge_roles = bridge.get_roles(int(guild_id)) or []

    # One member fetch; each member's role-id set for counting.
    member_role_ids = [
        {str(r.get("id")) for r in (m.get("roles") or [])}
        for m in MemberService().get_members(guild_id)
    ]

    roles = [

        serialize_role(
            role,
            member_role_ids
        )

        for role in bridge_roles

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
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "count":
            len(roles),

        "roles":
            roles

    })
