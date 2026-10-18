# web/blueprints/leaderboard.py
#
# Level/XP leaderboard for the web dashboard.

from flask import Blueprint, jsonify

from web.services.discord_state import discord_state, run_coro_threadsafe
from web.security.decorators import require_guild_access


leaderboard_api = Blueprint(
    "leaderboard",
    __name__,
    url_prefix="/api",
)


@leaderboard_api.get("/servers/<int:guild_id>/leaderboard")
@require_guild_access
def get_leaderboard(guild_id):
    bot = discord_state.bot
    if bot is None or not discord_state.ready:
        return jsonify({
            "success": False,
            "error": "Discord bot is not connected.",
        }), 503

    guild = bot.get_guild(int(guild_id))
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

    entries = []
    for user_id, udata in (db or {}).items():
        try:
            member = guild.get_member(int(user_id))
        except Exception:
            member = None

        entries.append({
            "user_id": str(user_id),
            "xp": udata.get("xp", 0) or 0,
            "level": udata.get("level", 1) or 1,
            "display_name": member.display_name if member else f"User {user_id}",
            "username": member.name if member else "unknown",
            "avatar": str(member.display_avatar.url) if member and member.display_avatar else None,
            "bot": bool(member and getattr(member, "bot", False)),
        })

    # Sort by XP descending
    entries.sort(key=lambda e: e["xp"], reverse=True)

    # Add rank
    for i, e in enumerate(entries):
        e["rank"] = i + 1

    return jsonify({
        "success": True,
        "guild_id": str(guild_id),
        "guild_name": guild.name,
        "count": len(entries),
        "leaderboard": entries[:100],  # top 100
    })
