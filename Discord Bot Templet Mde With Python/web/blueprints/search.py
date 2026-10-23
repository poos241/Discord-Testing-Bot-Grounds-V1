from flask import Blueprint, jsonify, request

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_manage, require_login, require_guild_member


search_api = Blueprint(
    "search",
    __name__
)


def get_guild(guild_id):

    bot = discord_state.get_bot()

    if bot is None:
        return None

    if not discord_state.ready:
        return None

    return bot.get_guild(
        int(guild_id)
    )


@search_api.get(
    "/api/servers/<int:guild_id>/search"
)
@require_guild_member
def search_server(guild_id):

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

    for member in guild.members:

        values = [

            str(member.id),

            member.name or "",

            member.display_name or "",

            member.nick or ""

        ]


        if any(
            query in value.lower()
            for value in values
        ):

            members.append({

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

    for channel in guild.channels:

        if query in channel.name.lower():

            channels.append({

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
                        0
                    ),

                "category":
                    (
                        channel.category.name
                        if channel.category
                        else None
                    )
            })


    # -----------------------------------------------------
    # ROLES
    # -----------------------------------------------------

    for role in guild.roles:

        if role.name == "@everyone":
            continue


        if (
            query in role.name.lower()
            or query in str(role.id)
        ):

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
                    role.managed,

                "mentionable":
                    role.mentionable
            })


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

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
