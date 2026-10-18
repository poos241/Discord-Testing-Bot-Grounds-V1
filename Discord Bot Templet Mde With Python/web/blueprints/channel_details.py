from flask import Blueprint, jsonify

from web.services.discord_state import discord_state
from web.security.decorators import require_guild_access, require_guild_manage, require_login


channel_details_api = Blueprint(
    "channel_details",
    __name__
)


def get_bot():

    return discord_state.get_bot()


def get_guild(guild_id):

    bot = get_bot()

    if bot is None:
        return None

    if not discord_state.ready:
        return None

    return bot.get_guild(
        int(guild_id)
    )


@channel_details_api.get(
    "/api/servers/<int:guild_id>/channels/<int:channel_id>/details"
)
@require_guild_access
@require_guild_manage
def channel_details(
    guild_id,
    channel_id
):

    guild = get_guild(
        guild_id
    )

    if guild is None:

        return jsonify({
            "success": False,
            "error": "Discord server not found."
        }), 404


    channel = guild.get_channel(
        int(channel_id)
    )

    if channel is None:

        return jsonify({
            "success": False,
            "error": "Channel not found."
        }), 404


    data = {

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

        "category_id":
            (
                str(channel.category_id)
                if getattr(
                    channel,
                    "category_id",
                    None
                )
                else None
            ),

        "category":
            (
                channel.category.name
                if getattr(
                    channel,
                    "category",
                    None
                )
                else None
            ),

        "topic":
            getattr(
                channel,
                "topic",
                None
            ),

        "nsfw":
            getattr(
                channel,
                "nsfw",
                False
            ),

        "slowmode_delay":
            getattr(
                channel,
                "slowmode_delay",
                0
            ),

        "created_at":
            (
                channel.created_at.isoformat()
                if getattr(
                    channel,
                    "created_at",
                    None
                )
                else None
            )
    }


    # -----------------------------------------------------
    # PERMISSIONS
    # -----------------------------------------------------

    permissions = []


    for role in guild.roles:

        try:

            overwrite = channel.overwrites_for(
                role
            )

            allowed = []

            denied = []


            for permission, value in overwrite:

                if value is True:

                    allowed.append(
                        permission
                    )

                elif value is False:

                    denied.append(
                        permission
                    )


            if allowed or denied:

                permissions.append({

                    "role_id":
                        str(role.id),

                    "role_name":
                        role.name,

                    "allowed":
                        allowed,

                    "denied":
                        denied
                })

        except Exception:
            continue


    data["permissions"] = permissions


    return jsonify({

        "success": True,

        "guild_id":
            str(guild.id),

        "channel":
            data
    })
