from flask import Blueprint, jsonify, request

import discord

from web.services import bridge
from web.services.event_store import event_store
from web.services.member_service import MemberService
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


explorer_api = Blueprint(
    "explorer",
    __name__
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
        return None, "Discord bot is not connected."

    guild = None
    try:
        guild = bridge.get_guild(int(guild_id))
    except Exception:
        guild = None

    if guild is None:
        return None, "Discord server not found."

    return guild, None


# =========================================================
# SERVER SEARCH
#
# GET
# /api/servers/<guild_id>/search?q=test
#
# Optional:
# type=all
# type=members
# type=channels
# type=roles
# =========================================================

@explorer_api.get(
    "/api/servers/<int:guild_id>/search"
)
@require_guild_moderator
def server_search(guild_id):

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


    query = request.args.get(
        "q",
        ""
    ).strip().lower()

    search_type = request.args.get(
        "type",
        "all"
    ).strip().lower()


    if not query:

        return jsonify({
            "success": False,
            "error": "Search query is required.",
            "guild_id": str(guild_id)
        }), 400


    if search_type not in (
        "all",
        "members",
        "channels",
        "roles"
    ):

        return jsonify({
            "success": False,
            "error": "Invalid search type.",
            "allowed": [
                "all",
                "members",
                "channels",
                "roles"
            ]
        }), 400


    results = {
        "members": [],
        "channels": [],
        "roles": []
    }


    # -----------------------------------------------------
    # MEMBERS
    # -----------------------------------------------------

    if search_type in (
        "all",
        "members"
    ):

        for member in MemberService().get_members(guild_id):

            username = (
                member.get("username") or ""
            ).lower()

            display_name = (
                member.get("display_name") or ""
            ).lower()

            nickname = (
                member.get("nickname") or ""
            ).lower()

            member_id = str(
                member.get("id")
            )

            if (
                query in username
                or query in display_name
                or query in nickname
                or query in member_id
            ):

                results["members"].append({

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

                    "avatar":
                        member.get("avatar")
                })


    # -----------------------------------------------------
    # CHANNELS
    # -----------------------------------------------------

    if search_type in (
        "all",
        "channels"
    ):

        for channel in (bridge.get_channels(int(guild_id)) or []):

            name = (
                channel.get("name") or ""
            ).lower()

            channel_id = str(
                channel.get("id")
            )

            if (
                query in name
                or query in channel_id
            ):

                results["channels"].append({

                    "id":
                        str(channel.get("id")),

                    "name":
                        channel.get("name"),

                    "type":
                        str(channel.get("type")),

                    "position":
                        channel.get("position"),

                    "category":
                        channel.get("category"),

                    "category_id":
                        channel.get("category_id")
                })


    # -----------------------------------------------------
    # ROLES
    # -----------------------------------------------------

    if search_type in (
        "all",
        "roles"
    ):

        for role in (bridge.get_roles(int(guild_id)) or []):

            name = (
                role.get("name") or ""
            ).lower()

            role_id = str(
                role.get("id")
            )

            if (
                query in name
                or query in role_id
            ):

                results["roles"].append({

                    "id":
                        str(role.get("id")),

                    "name":
                        role.get("name"),

                    "position":
                        role.get("position"),

                    "color":
                        role.get("color"),

                    "managed":
                        role.get("managed"),

                    "mentionable":
                        role.get("mentionable"),

                    "hoist":
                        role.get("hoist")
                })


    total = (
        len(results["members"])
        + len(results["channels"])
        + len(results["roles"])
    )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "query":
            query,

        "type":
            search_type,

        "total":
            total,

        "results":
            results
    })


# =========================================================
# SERVER PERMISSIONS
#
# GET
# /api/servers/<guild_id>/permissions
# =========================================================

@explorer_api.get(
    "/api/servers/<int:guild_id>/permissions"
)
@require_guild_moderator
def server_permissions(guild_id):

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


    administrator_roles = []
    dangerous_roles = []


    dangerous_permissions = [
        "administrator",
        "manage_guild",
        "manage_roles",
        "manage_channels",
        "ban_members",
        "kick_members",
        "moderate_members",
        "manage_messages",
        "manage_webhooks"
    ]


    for role in (bridge.get_roles(int(guild_id)) or []):

        if role.get("name") == "@everyone":
            continue

        role_perms = discord.Permissions(
            int(role.get("permissions") or 0)
        )

        enabled = []

        for permission in dangerous_permissions:

            if getattr(
                role_perms,
                permission,
                False
            ):

                enabled.append(
                    permission
                )


        if role_perms.administrator:

            administrator_roles.append({

                "id":
                    str(role.get("id")),

                "name":
                    role.get("name"),

                "position":
                    role.get("position"),

                "managed":
                    role.get("managed")
            })


        if enabled:

            dangerous_roles.append({

                "id":
                    str(role.get("id")),

                "name":
                    role.get("name"),

                "position":
                    role.get("position"),

                "permissions":
                    enabled
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "owner_id":
            (
                str(guild.get("owner_id"))
                if guild.get("owner_id")
                else None
            ),

        "administrator_roles":
            administrator_roles,

        "dangerous_roles":
            dangerous_roles,

        "dangerous_permission_count":
            len(dangerous_permissions)
    })


# =========================================================
# SERVER ACTIVITY
#
# GET
# /api/servers/<guild_id>/activity
#
# Optional:
# ?limit=50
# ?category=messages
# ?event_type=message_delete
# ?user_id=123
# ?channel_id=123
# =========================================================

@explorer_api.get(
    "/api/servers/<int:guild_id>/activity"
)
@require_guild_moderator
def server_activity(guild_id):

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


    limit = request.args.get(
        "limit",
        50,
        type=int
    )

    limit = max(
        1,
        min(
            limit,
            500
        )
    )


    category = request.args.get(
        "category"
    )

    event_type = request.args.get(
        "event_type"
    )

    user_id = request.args.get(
        "user_id"
    )

    channel_id = request.args.get(
        "channel_id"
    )


    events = event_store.query(

        limit=limit,

        guild_id=guild.get("id"),

        category=category,

        event_type=event_type,

        user_id=user_id,

        channel_id=channel_id
    )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "count":
            len(events),

        "filters": {

            "category":
                category,

            "event_type":
                event_type,

            "user_id":
                user_id,

            "channel_id":
                channel_id,

            "limit":
                limit
        },

        "events":
            events
    })


# =========================================================
# SERVER TOP MEMBERS
#
# GET
# /api/servers/<guild_id>/members/top
# =========================================================

@explorer_api.get(
    "/api/servers/<int:guild_id>/members/top"
)
@require_guild_moderator
def top_members(guild_id):

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


    limit = request.args.get(
        "limit",
        20,
        type=int
    )

    limit = max(
        1,
        min(
            limit,
            100
        )
    )


    # ISO timestamps sort chronologically as plain strings.
    members = sorted(
        MemberService().get_members(guild_id),
        key=lambda member: (
            member.get("joined_at")
            or member.get("created_at")
            or ""
        )
    )


    members = members[:limit]


    result = []


    for member in members:

        result.append({

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

            "joined_at":
                member.get("joined_at"),

            "avatar":
                member.get("avatar")
        })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "guild_name":
            guild.get("name"),

        "count":
            len(result),

        "members":
            result
    })
