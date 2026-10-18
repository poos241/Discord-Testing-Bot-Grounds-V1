from flask import Blueprint, jsonify, request

from web.services.discord_state import discord_state
from web.services.event_store import event_store
from web.security.decorators import require_guild_access, require_guild_manage, require_login


explorer_api = Blueprint(
    "explorer",
    __name__
)


# =========================================================
# HELPERS
# =========================================================

def get_bot():

    return discord_state.get_bot()


def get_guild(guild_id):

    bot = get_bot()

    if bot is None:
        return None, "Discord bot is not connected."

    if not discord_state.ready:
        return None, "Discord bot is not ready."

    guild = bot.get_guild(
        int(guild_id)
    )

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
@require_guild_access
@require_guild_manage
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

        for member in guild.members:

            username = (
                member.name or ""
            ).lower()

            display_name = (
                member.display_name or ""
            ).lower()

            nickname = (
                member.nick or ""
            ).lower()

            member_id = str(
                member.id
            )

            if (
                query in username
                or query in display_name
                or query in nickname
                or query in member_id
            ):

                results["members"].append({

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

                    "avatar":
                        (
                            str(member.display_avatar.url)
                            if member.display_avatar
                            else None
                        )
                })


    # -----------------------------------------------------
    # CHANNELS
    # -----------------------------------------------------

    if search_type in (
        "all",
        "channels"
    ):

        for channel in guild.channels:

            name = (
                channel.name or ""
            ).lower()

            channel_id = str(
                channel.id
            )

            if (
                query in name
                or query in channel_id
            ):

                results["channels"].append({

                    "id":
                        str(channel.id),

                    "name":
                        channel.name,

                    "type":
                        str(channel.type),

                    "position":
                        getattr(
                            channel,
                            "position",
                            None
                        ),

                    "category":
                        (
                            channel.category.name
                            if channel.category
                            else None
                        ),

                    "category_id":
                        (
                            str(channel.category.id)
                            if channel.category
                            else None
                        )
                })


    # -----------------------------------------------------
    # ROLES
    # -----------------------------------------------------

    if search_type in (
        "all",
        "roles"
    ):

        for role in guild.roles:

            name = (
                role.name or ""
            ).lower()

            role_id = str(
                role.id
            )

            if (
                query in name
                or query in role_id
            ):

                results["roles"].append({

                    "id":
                        str(role.id),

                    "name":
                        role.name,

                    "position":
                        role.position,

                    "color":
                        str(role.color),

                    "managed":
                        role.managed,

                    "mentionable":
                        role.mentionable,

                    "hoist":
                        role.hoist
                })


    total = (
        len(results["members"])
        + len(results["channels"])
        + len(results["roles"])
    )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

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
@require_guild_access
@require_guild_manage
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


    for role in guild.roles:

        if role.name == "@everyone":
            continue


        enabled = []

        for permission in dangerous_permissions:

            if getattr(
                role.permissions,
                permission,
                False
            ):

                enabled.append(
                    permission
                )


        if role.permissions.administrator:

            administrator_roles.append({

                "id":
                    str(role.id),

                "name":
                    role.name,

                "position":
                    role.position,

                "managed":
                    role.managed
            })


        if enabled:

            dangerous_roles.append({

                "id":
                    str(role.id),

                "name":
                    role.name,

                "position":
                    role.position,

                "permissions":
                    enabled
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "owner_id":
            (
                str(guild.owner_id)
                if guild.owner_id
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
@require_guild_access
@require_guild_manage
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

        guild_id=guild.id,

        category=category,

        event_type=event_type,

        user_id=user_id,

        channel_id=channel_id
    )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

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
@require_guild_access
@require_guild_manage
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


    members = sorted(
        guild.members,
        key=lambda member: (
            member.joined_at
            if member.joined_at
            else member.created_at
        )
    )


    members = members[:limit]


    result = []


    for member in members:

        result.append({

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

            "joined_at":
                (
                    member.joined_at.isoformat()
                    if member.joined_at
                    else None
                ),

            "avatar":
                (
                    str(member.display_avatar.url)
                    if member.display_avatar
                    else None
                )
        })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "count":
            len(result),

        "members":
            result
    })
