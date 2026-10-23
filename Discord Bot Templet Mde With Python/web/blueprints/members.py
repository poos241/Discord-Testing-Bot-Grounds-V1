from flask import Blueprint, jsonify, request

from web.services.discord_state import discord_state
from web.services.member_service import MemberService
from web.blueprints.channels import get_bot
from web.security.decorators import require_guild_manage, require_login, require_guild_member


members_api = Blueprint(
    "members",
    __name__,
    url_prefix="/api"
)


def paginate(items, page, per_page):

    try:
        page = int(page)
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(per_page)
    except (TypeError, ValueError):
        per_page = 50

    page = max(
        page,
        1
    )

    per_page = max(
        min(per_page, 100),
        1
    )

    total = len(items)

    start = (
        page - 1
    ) * per_page

    end = start + per_page

    return {
        "items":
            items[start:end],

        "page":
            page,

        "per_page":
            per_page,

        "total":
            total,

        "total_pages":
            (
                (total + per_page - 1)
                // per_page
            ),

        "has_next":
            end < total,

        "has_previous":
            page > 1
    }


# =========================================================
# BOT
# =========================================================

def get_service():

    bot = get_bot()

    if bot is None:
        return None

    return MemberService(
        bot
    )

# =========================================================
# SERVICE
# =========================================================

def get_service():

    return MemberService(
        get_bot()
    )


# =========================================================
# CHECK BOT
# =========================================================

def check_bot():

    bot = get_bot()

    if bot is None:

        return None, jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    if not discord_state.ready:

        return None, jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503

    return bot, None, None


# =========================================================
# GET MEMBERS
#
# GET /api/members?guild_id=123
# =========================================================

@members_api.get("/members")
@require_login
def get_members():

    guild_id = request.args.get(
        "guild_id",
        type=int
    )

    if guild_id is None:

        return jsonify({
            "success": False,
            "error": "guild_id is required"
        }), 400


    if discord_state.bot is None:

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503


    if not discord_state.ready:

        return jsonify({
            "success": False,
            "error": "Discord bot is not ready."
        }), 503


    service = get_service()

    members = service.get_members(
        guild_id
    )


    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "count":
            len(members),

        "members":
            [
                service.serialize_member(m)
                for m in members
            ]

    })


# =========================================================
# GET MEMBER
#
# GET /api/members/<user_id>?guild_id=123
# =========================================================

@members_api.get("/members/<int:user_id>")
@require_login
def get_member(user_id):

    bot, error, status = check_bot()

    if error:

        return error, status

    guild_id = request.args.get(
        "guild_id",
        type=int
    )

    if guild_id is None:

        return jsonify({
            "success": False,
            "error": "guild_id is required"
        }), 400

    service = get_service()

    guild = service.get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id)
        }), 404

    member = service.get_member(
        guild_id,
        user_id
    )

    if member is None:

        return jsonify({
            "success": False,
            "error": "Member not found.",
            "user_id": str(user_id),
            "guild_id": str(guild_id)
        }), 404

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "member":
            service.serialize_member(
                member
            )

    })


# =========================================================
# SERVER MEMBER
#
# GET /api/servers/<guild_id>/members/<user_id>
# =========================================================

@members_api.get(
    "/servers/<int:guild_id>/members/<int:user_id>"
)
@require_guild_member
def get_server_member(
    guild_id,
    user_id
):

    bot, error, status = check_bot()

    if error:

        return error, status

    service = get_service()

    guild = service.get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id)
        }), 404

    member = service.get_member(
        guild_id,
        user_id
    )

    if member is None:

        return jsonify({
            "success": False,
            "error": "Member not found.",
            "guild_id": str(guild_id),
            "user_id": str(user_id)
        }), 404

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "member":
            service.serialize_member(
                member
            )

    })


# =========================================================
# SERVER MEMBERS
#
# GET /api/servers/<guild_id>/members
# =========================================================

@members_api.get(
    "/servers/<int:guild_id>/members"
)
@require_guild_member
def get_server_members(guild_id):

    bot, error, status = check_bot()

    if error:

        return error, status

    service = get_service()

    guild = service.get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found.",
            "guild_id": str(guild_id)
        }), 404

    query = request.args.get(
        "search",
        ""
    ).strip()

    if query:

        members = service.search_members(
            guild_id,
            query
        )

    else:

        members = service.get_members(
            guild_id
        )

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "count":
            len(members),

        "search":
            query or None,

        "members":
            [
                service.serialize_member(m)
                for m in members
            ]

    })
    
# ============================================================
# MEMBER STATISTICS
#
# /api/servers/<guild_id>/members/summary
# ============================================================

@members_api.get(
    "/servers/<int:guild_id>/members/summary"
)
@require_guild_member
def member_summary(guild_id):

    service = get_service()

    guild = service.get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404

    members = service.get_members(
        guild_id
    )

    humans = [
        member
        for member in members
        if not member.bot
    ]

    bots = [
        member
        for member in members
        if member.bot
    ]

    online = 0
    idle = 0
    dnd = 0
    offline = 0

    for member in members:

        status = str(
            member.status
        ).lower()

        if status == "online":
            online += 1

        elif status == "idle":
            idle += 1

        elif status in (
            "dnd",
            "do_not_disturb"
        ):
            dnd += 1

        else:
            offline += 1

    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "guild_name":
            guild.name,

        "summary": {

            "total":
                len(members),

            "humans":
                len(humans),

            "bots":
                len(bots),

            "online":
                online,

            "idle":
                idle,

            "dnd":
                dnd,

            "offline":
                offline
        }
    })
    
# ============================================================
# SEARCH MEMBERS
#
# /api/servers/<guild_id>/members/search?q=test
# ============================================================

@members_api.get(
    "/servers/<int:guild_id>/members/search"
)
@require_guild_member
def search_server_members(guild_id):

    query = request.args.get(
        "q",
        ""
    ).strip()

    if not query:

        return jsonify({
            "success": False,
            "error": "Search query is required."
        }), 400

    service = get_service()

    members = service.search_members(
        guild_id,
        query
    )

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "query":
            query,

        "count":
            len(members),

        "members":
            [
                service.serialize_member(m)
                for m in members
            ]

    })
