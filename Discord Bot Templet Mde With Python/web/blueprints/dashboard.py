from flask import Blueprint, jsonify

from web.services.server_service import ServerService
from web.services import bridge
from web.security.decorators import require_guild_manage, require_login, require_guild_moderator


dashboard_api = Blueprint(
    "dashboard",
    __name__
)


# ============================================================
# BOT
# ============================================================

def get_bot():
    """Kept for call-site compat. Always None now -- there is no live
    bot object in this process."""
    return None


# ============================================================
# DASHBOARD
#
# GET /api/servers/<guild_id>/dashboard
# ============================================================

@dashboard_api.get(
    "/api/servers/<int:guild_id>/dashboard"
)
@require_guild_moderator
def server_dashboard(
    guild_id
):

    if not bridge.bot_is_ready():

        return jsonify({

            "success": False,

            "error":
                "Discord bot is not connected."

        }), 503

    guild = None
    try:
        guild = bridge.get_guild(int(guild_id))
    except Exception:
        guild = None

    if guild is None:

        print(
            f"[Dashboard] Guild not found: {guild_id}"
        )

        print(
            "[Dashboard] Connected guilds:"
        )

        try:
            connected = bridge.get_guilds() or []
        except Exception:
            connected = []
        for connected_guild in connected:

            print(
                f"  - {connected_guild.get('name')} "
                f"({connected_guild.get('id')})"
            )


        return jsonify({

            "success": False,

            "error":
                "Discord server not found",

            "guild_id":
                str(guild_id)

        }), 404


    service = ServerService()


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
