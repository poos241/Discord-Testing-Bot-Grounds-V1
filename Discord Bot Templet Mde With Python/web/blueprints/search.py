from flask import Blueprint, jsonify, request

from web.services import bridge
from web.services.member_service import MemberService
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


search_api = Blueprint(
    "search",
    __name__
)


def get_guild(guild_id):

    if not bridge.bot_is_ready():
        return None

    try:
        return bridge.get_guild(int(guild_id))
    except Exception:
        return None


@search_api.get(
    "/api/servers/<int:guild_id>/search"
)
@require_guild_moderator
def search_server(guild_id):

    if not bridge.bot_is_ready():

        return jsonify({
            "success": False,
            "error": "Discord bot is not connected."
        }), 503

    guild = get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    query = request.args.get(
        "q",
        ""
    ).strip().lower()


    if not query:

        return jsonify({

            "success": True,

            "query": "",

            "members": [],

            "channels": [],

            "roles": [],

            "total": 0

        })


    members = []
    channels = []
    roles = []


    # -----------------------------------------------------
    # MEMBERS
    # -----------------------------------------------------

    for member in MemberService().get_members(guild_id):

        values = [

            str(member.get("id")),

            member.get("username") or "",

            member.get("display_name") or "",

            member.get("nickname") or ""

        ]


        if any(
            query in value.lower()
            for value in values
        ):

            members.append({

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

    for channel in (bridge.get_channels(int(guild_id)) or []):

        if query in (channel.get("name") or "").lower():

            channels.append({

                "id":
                    str(channel.get("id")),

                "name":
                    channel.get("name"),

                "type":
                    str(channel.get("type")),

                "position":
                    channel.get("position", 0),

                "category":
                    channel.get("category")
            })


    # -----------------------------------------------------
    # ROLES
    # -----------------------------------------------------

    for role in (bridge.get_roles(int(guild_id)) or []):

        if role.get("name") == "@everyone":
            continue


        if (
            query in (role.get("name") or "").lower()
            or query in str(role.get("id"))
        ):

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
                    role.get("managed"),

                "mentionable":
                    role.get("mentionable")
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.get("id")),

        "query":
            query,

        "members":
            members[:50],

        "channels":
            channels[:50],

        "roles":
            roles[:50],

        "total":
            len(members)
            + len(channels)
            + len(roles)

    })
