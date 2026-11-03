# web/blueprints/leaderboard.py
#
# Level/XP leaderboard for the web dashboard.

from flask import Blueprint, jsonify

from web.services import bridge
from web.services.discord_state import run_coro_threadsafe
from web.services.member_service import MemberService
from web.security.decorators import require_guild_moderator


leaderboard_api = Blueprint(
    "leaderboard",
    __name__,
    url_prefix="/api",
)


@leaderboard_api.get("/servers/<int:guild_id>/leaderboard")
@require_guild_moderator
def get_leaderboard(guild_id):
    if not bridge.bot_is_ready():
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
        }), 503

    guild = bridge.get_guild(int(guild_id))
    if guild is None:
        return jsonify({
            "success": False,
            "error": "Discord server not found.",
        }), 404

    # Load level data
    try:
        from data.DB.Storage.storage import get_levels
        db = run_coro_threadsafe(
            get_levels(str(guild_id))
        ).result(timeout=10)
    except Exception as e:
        return jsonify({
            "success": False,
            "error": f"Could not load XP data: {e}",
        }), 500

    # One member fetch for the whole guild (bridge pages it), then
    # look users up in that map instead of one lookup per user.
    try:
        members = MemberService().get_members(guild_id)
    except Exception:
        members = []
    by_id = {
        str(m.get("id")): m
        for m in members
    }

    entries = []
    for user_id, udata in (db or {}).items():
        member = by_id.get(str(user_id))

        entries.append({
            "user_id": str(user_id),
            "xp": udata.get("xp", 0) or 0,
            "level": udata.get("level", 1) or 1,
            "display_name": (
                member.get("display_name") or member.get("username")
                if member else f"User {user_id}"
            ),
            "username": member.get("username") if member else "unknown",
            "avatar": member.get("avatar") if member else None,
            "bot": bool(member and member.get("bot", False)),
        })

    # Sort by XP descending
    entries.sort(key=lambda e: e["xp"], reverse=True)

    # Add rank
    for i, e in enumerate(entries):
        e["rank"] = i + 1

    return jsonify({
        "success": True,
        "guild_id": str(guild_id),
        "guild_name": guild.get("name"),
        "count": len(entries),
        "leaderboard": entries[:100],  # top 100
    })
