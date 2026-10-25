"""End-user profile customization API.

Stores per-user profile settings in ``data/profiles.json``
(created at runtime, never committed), keyed by Discord user ID.

Also serves bot stats (level/XP, daily streaks, Eat It or Yeet It)
aggregated across the bot's guilds, derives achievement badges
from those stats, and serves public profiles for users who opt in.
"""

import json
import os
import re
import secrets

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from web.blueprints.auth import get_csrf_token
from web.security.decorators import require_login
from web.services.discord_state import discord_state, run_coro_threadsafe


profiles_api = Blueprint(
    "profiles",
    __name__,
    url_prefix="/api",
)


# data/*.json lives next to the bot's other data files:
# <bot root>/data/
DATA_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
    )
)
PROFILES_PATH = os.path.join(
    DATA_DIR,
    "profiles.json",
)
EATYEET_PATH = os.path.join(
    DATA_DIR,
    "eatyeet_stats.json",
)

MAX_BIO_LEN = 500
MAX_STATUS_LEN = 120
MAX_URL_LEN = 500
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_RE = re.compile(r"^https?://\S+$")
SOCIAL_FIELDS = ("twitch", "youtube", "twitter", "website")

DEFAULT_PROFILE = {
    "bio": "",
    "accent": "#5865F2",
    "banner": "",
    "status": "",
    "socials": {},
    "public": False,
}


# =========================================================
# PROFILE STORAGE
# =========================================================

def _load_profiles():

    try:

        with open(
            PROFILES_PATH,
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):

            return data

    except (OSError, ValueError):

        pass

    return {}


def _save_profiles(data):

    os.makedirs(
        DATA_DIR,
        exist_ok=True,
    )

    tmp_path = PROFILES_PATH + ".tmp"

    with open(
        tmp_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
        )

    os.replace(
        tmp_path,
        PROFILES_PATH,
    )


def _clean_profile(saved):

    """Merge a saved profile over the defaults, validating fields."""

    profile = {
        "bio": str(saved.get("bio", ""))[:MAX_BIO_LEN],
        "accent": saved.get("accent", DEFAULT_PROFILE["accent"]),
        "banner": str(saved.get("banner", ""))[:MAX_URL_LEN],
        "status": str(saved.get("status", ""))[:MAX_STATUS_LEN],
        "socials": {},
        "public": bool(saved.get("public", False)),
    }

    if not ACCENT_RE.match(str(profile["accent"])):

        profile["accent"] = DEFAULT_PROFILE["accent"]

    if not URL_RE.match(profile["banner"]):

        profile["banner"] = ""

    socials = saved.get("socials", {})

    if isinstance(socials, dict):

        for field in SOCIAL_FIELDS:

            url = str(socials.get(field, "")).strip()[:MAX_URL_LEN]

            if url and URL_RE.match(url):

                profile["socials"][field] = url

    return profile


def _check_csrf():

    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or ""
    ).strip()

    expected = get_csrf_token()

    if not supplied or not secrets.compare_digest(supplied, expected):

        return jsonify({
            "success": False,
            "error": "Invalid CSRF token.",
        }), 403

    return None


# =========================================================
# BOT STATS
# =========================================================

def _load_eatyeet():

    try:

        with open(
            EATYEET_PATH,
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):

            return data

    except (OSError, ValueError):

        pass

    return {}


def get_user_stats(user_id):

    """Aggregate a user's stats across every guild the bot is in.

    Returns per-guild entries plus totals. Empty stats (no level
    data anywhere) still return a valid structure.
    """

    user_id = str(user_id)
    bot = discord_state.bot

    per_guild = []
    total_xp = 0
    total_played = 0
    total_points = 0
    total_majority = 0
    best_level = 0
    best_streak = 0
    best_game_streak = 0

    eatyeet = _load_eatyeet()

    if bot is None or not discord_state.ready:

        return {
            "per_guild": per_guild,
            "totals": {
                "xp": 0,
                "level": 0,
                "played": 0,
                "points": 0,
                "majority": 0,
                "daily_streak": 0,
                "best_game_streak": 0,
            },
            "bot_ready": False,
        }

    for guild in bot.guilds:

        gid = str(guild.id)

        try:

            from data.DB.Storage.storage import get_levels

            db = run_coro_threadsafe(
                get_levels(gid)
            ).result(timeout=10)

        except Exception:

            db = {}

        entry = db.get(user_id) if isinstance(db, dict) else None

        if not isinstance(entry, dict):

            continue

        xp = int(entry.get("xp", 0) or 0)
        level = int(entry.get("level", 1) or 1)
        daily_streak = int(entry.get("daily_streak", 0) or 0)

        # Rank within this guild (XP descending, numeric user ids only).
        ranked = sorted(
            (
                (uid, udata)
                for uid, udata in db.items()
                if uid.isdigit()
                and isinstance(udata, dict)
            ),
            key=lambda kv: int(kv[1].get("xp", 0) or 0),
            reverse=True,
        )

        rank = None

        for i, (uid, _udata) in enumerate(ranked):

            if uid == user_id:

                rank = i + 1
                break

        game = eatyeet.get(gid, {}).get("users", {}).get(user_id, {})

        if not isinstance(game, dict):

            game = {}

        played = int(game.get("played", 0) or 0)
        points = int(game.get("points", 0) or 0)
        majority = int(game.get("majority", 0) or 0)
        game_streak = int(game.get("best_streak", 0) or 0)

        per_guild.append({
            "guild_id": gid,
            "guild_name": guild.name,
            "guild_icon": str(guild.icon.url) if guild.icon else None,
            "xp": xp,
            "level": level,
            "rank": rank,
            "daily_streak": daily_streak,
            "played": played,
            "points": points,
            "majority": majority,
            "best_game_streak": game_streak,
        })

        total_xp += xp
        total_played += played
        total_points += points
        total_majority += majority
        best_level = max(best_level, level)
        best_streak = max(best_streak, daily_streak)
        best_game_streak = max(best_game_streak, game_streak)

    return {
        "per_guild": per_guild,
        "totals": {
            "xp": total_xp,
            "level": best_level,
            "played": total_played,
            "points": total_points,
            "majority": total_majority,
            "daily_streak": best_streak,
            "best_game_streak": best_game_streak,
        },
        "bot_ready": True,
    }


# =========================================================
# BADGES
# =========================================================

BADGE_DEFS = [
    ("level_5", "⭐", "Level 5", "Reached level 5"),
    ("level_10", "🌟", "Level 10", "Reached level 10"),
    ("level_25", "💎", "Level 25", "Reached level 25"),
    ("level_50", "👑", "Level 50", "Reached level 50"),
    ("first_game", "🎮", "First Game", "Played a round of Eat It or Yeet It"),
    ("regular", "🎯", "Regular Player", "Played 25 rounds of Eat It or Yeet It"),
    ("century", "🏆", "Century Club", "Scored 100 Eat It or Yeet It points"),
    ("streak_7", "🔥", "7-Day Streak", "Kept a 7-day daily streak going"),
    ("crowd", "👥", "Crowd Favorite", "Voted with the majority 10 times"),
]


def get_badges(stats):

    """Derive earned badges from aggregated stats."""

    totals = stats.get("totals", {})
    earned = []

    checks = {
        "level_5": totals.get("level", 0) >= 5,
        "level_10": totals.get("level", 0) >= 10,
        "level_25": totals.get("level", 0) >= 25,
        "level_50": totals.get("level", 0) >= 50,
        "first_game": totals.get("played", 0) >= 1,
        "regular": totals.get("played", 0) >= 25,
        "century": totals.get("points", 0) >= 100,
        "streak_7": totals.get("daily_streak", 0) >= 7,
        "crowd": totals.get("majority", 0) >= 10,
    }

    for key, icon, name, desc in BADGE_DEFS:

        earned.append({
            "key": key,
            "icon": icon,
            "name": name,
            "description": desc,
            "earned": bool(checks.get(key, False)),
        })

    return earned


# =========================================================
# SELF PROFILE
# =========================================================

@profiles_api.get(
    "/profile"
)
@require_login
def get_profile():

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    saved = _load_profiles().get(user_id, {})
    profile = _clean_profile(saved)

    return jsonify({

        "success": True,

        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "global_name": user.get("global_name"),
            "avatar": user.get("avatar"),
        },

        "profile": profile,

    })


@profiles_api.post(
    "/profile"
)
@require_login
def save_profile():

    denied = _check_csrf()

    if denied is not None:

        return denied

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    if not user_id:

        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    body = request.get_json(silent=True) or {}

    incoming = {
        "bio": body.get("bio", ""),
        "accent": body.get("accent", ""),
        "banner": body.get("banner", ""),
        "status": body.get("status", ""),
        "socials": body.get("socials", {}),
        "public": body.get("public", False),
    }

    profile = _clean_profile(incoming)

    data = _load_profiles()
    data[user_id] = profile

    try:

        _save_profiles(data)

    except OSError as exc:

        print(
            "[Profiles API] Failed to save "
            f"profiles.json: {exc}"
        )

        return jsonify({
            "success": False,
            "error": "Could not save profile.",
        }), 500

    return jsonify({

        "success": True,

        "profile": profile,

    })


# =========================================================
# SELF STATS + BADGES
# =========================================================

@profiles_api.get(
    "/profile/stats"
)
@require_login
def get_self_stats():

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    stats = get_user_stats(user_id)

    return jsonify({

        "success": True,

        "stats": stats,

        "badges": get_badges(stats),

    })


# =========================================================
# PUBLIC PROFILE
# =========================================================

@profiles_api.get(
    "/profile/public/<user_id>"
)
def get_public_profile(user_id):

    saved = _load_profiles().get(str(user_id), {})

    if not saved or not saved.get("public"):

        return jsonify({
            "success": False,
            "error": "Profile not found or not public.",
        }), 404

    profile = _clean_profile(saved)

    # Display name + avatar from the bot (shared servers only).
    display_name = None
    avatar_url = None
    bot = discord_state.bot

    if bot is not None and discord_state.ready:

        try:

            member_user = bot.get_user(int(user_id))

            if member_user is not None:

                display_name = (
                    member_user.global_name
                    or member_user.name
                )
                avatar_url = str(member_user.display_avatar.url)

        except (ValueError, TypeError):

            pass

    stats = get_user_stats(user_id)

    return jsonify({

        "success": True,

        "user": {
            "id": str(user_id),
            "display_name": display_name,
            "avatar_url": avatar_url,
        },

        "profile": profile,

        "stats": stats,

        "badges": get_badges(stats),

    })
