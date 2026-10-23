from flask import Blueprint, jsonify

from web.services.server_service import ServerService
from web.services.discord_state import discord_state
from web.security.decorators import require_guild_manage, require_login, require_guild_member


dashboard_api = Blueprint(
    "dashboard",
    __name__
)


# ============================================================
# BOT
# ============================================================

def get_bot():

    return discord_state.get_bot()


# ============================================================
# DASHBOARD
#
# GET /api/servers/<guild_id>/dashboard
# ============================================================

@dashboard_api.get(
    "/api/servers/<int:guild_id>/dashboard"
)
@require_guild_member
def server_dashboard(
    guild_id
):

    bot = get_bot()


    if bot is None:

        return jsonify({

            "success": False,

            "error":
                "Discord bot is not connected."

        }), 503


    if not bot.is_ready():

        return jsonify({

            "success": False,

            "error":
                "Discord bot is not ready."

        }), 503


    guild = bot.get_guild(
        int(guild_id)
    )


    if guild is None:

        print(
            f"[Dashboard] Guild not found: {guild_id}"
        )

        print(
            "[Dashboard] Connected guilds:"
        )

        for connected_guild in bot.guilds:

            print(
                f"  - {connected_guild.name} "
                f"({connected_guild.id})"
            )


        return jsonify({

            "success": False,

            "error":
                "Discord server not found",

            "guild_id":
                str(guild_id)

        }), 404


    service = ServerService(
        bot
    )


    dashboard = service.get_dashboard(
        guild_id
    )


    if dashboard is None:

        return jsonify({

            "success": False,

            "error":
                "Could not build server dashboard."

        }), 500


    response = {"success": True}
    response.update(dashboard)
    return jsonify(response)
