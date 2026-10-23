from flask import Blueprint, jsonify

from web.services.statistics import StatisticsService
from web.security.decorators import require_guild_manage, require_login, require_guild_member


statistics_api = Blueprint(
    "statistics",
    __name__,
    url_prefix="/api"
)


@statistics_api.get(
    "/servers/<int:guild_id>/statistics"
)
@require_guild_member
def server_statistics(guild_id):

    data = StatisticsService.get(
        guild_id
    )

    return jsonify({

        "success": True,

        "guild_id":
            str(guild_id),

        "statistics":
            data

    })
