"""End-user profile customization API.

Profile settings live in the bot's SQLite database
(``data/bot.db``, ``profiles`` table) — migrated from the old
``data/profiles.json`` on first read (the JSON file is kept as a
``profiles.json.migrated`` backup and never read again).

Also serves bot stats (level/XP, daily streaks, Eat It or Yeet It)
aggregated across the bot's guilds, derives achievement badges
from those stats, serves the per-user activity feed, and serves
public profiles for users who opt in.
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
LEGACY_PROFILES_PATH = os.path.join(
    DATA_DIR,
    "profiles.json",
)
LEGACY_BACKUP_PATH = os.path.join(
    DATA_DIR,
    "profiles.json.migrated",
)
EATYEET_PATH = os.path.join(
    DATA_DIR,
    "eatyeet_stats.json",
)

MAX_BIO_LEN = 500
MAX_STATUS_LEN = 120
MAX_URL_LEN = 500
MAX_PRONOUNS_LEN = 40
MAX_DISPLAY_NAME_LEN = 64
MAX_TAGS = 10
MAX_SOCIAL_LINKS = 10
MAX_TAG_LEN = 24
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
URL_RE = re.compile(r"^https?://\S+$")
SOCIAL_FIELDS = ("twitch", "youtube", "twitter", "website")
FEATURED_STATS = ("level", "xp", "played", "points", "daily_streak")

DEFAULT_PROFILE = {
    "bio": "",
    "accent": "#5865F2",
    "banner": "",
    "status": "",
    "avatar_url": "",
    "background_url": "",
    "pronouns": "",
    "display_name": "",
    "featured_badge": "",
    "featured_stat": "",
    "socials": [],
    "tags": [],
    "public": False,
}


# =========================================================
# PROFILE STORAGE (SQLite, with one-time JSON migration)
# =========================================================

_MIGRATION_DONE = False


def _clean_profile(saved):

    """Validate a profile dict (from DB or JSON) into canonical shape."""

    if not isinstance(saved, dict):

        saved = {}

    profile = {
        "bio": str(saved.get("bio", ""))[:MAX_BIO_LEN],
        "accent": saved.get("accent", DEFAULT_PROFILE["accent"]),
        "banner": str(saved.get("banner", ""))[:MAX_URL_LEN],
        "status": str(saved.get("status", ""))[:MAX_STATUS_LEN],
        "avatar_url": str(saved.get("avatar_url", ""))[:MAX_URL_LEN],
        "background_url": str(saved.get("background_url", ""))[:MAX_URL_LEN],
        "pronouns": str(saved.get("pronouns", ""))[:MAX_PRONOUNS_LEN],
        "display_name": str(saved.get("display_name", ""))[:MAX_DISPLAY_NAME_LEN],
        "featured_badge": str(saved.get("featured_badge", "")),
        "featured_stat": str(saved.get("featured_stat", "")),
        "socials": [],
        "tags": [],
        "public": bool(saved.get("public", False)),
    }

    if not ACCENT_RE.match(str(profile["accent"])):

        profile["accent"] = DEFAULT_PROFILE["accent"]

    for field in ("banner", "avatar_url", "background_url"):

        if not URL_RE.match(profile[field]):

            profile[field] = ""

    socials = saved.get("socials", [])

    if isinstance(socials, dict):

        # Legacy shape: {platform: url} -> ordered list of urls.
        socials = [socials.get(field, "") for field in SOCIAL_FIELDS]

    if isinstance(socials, list):

        for url in socials[:MAX_SOCIAL_LINKS]:

            url = str(url).strip()[:MAX_URL_LEN]

            if url and URL_RE.match(url) and url not in profile["socials"]:

                profile["socials"].append(url)

    tags = saved.get("tags", [])

    if isinstance(tags, list):

        for tag in tags[:MAX_TAGS]:

            tag = str(tag).strip()[:MAX_TAG_LEN]

            if tag and tag not in profile["tags"]:

                profile["tags"].append(tag)

    if profile["featured_badge"] not in {b[0] for b in BADGE_DEFS}:

        profile["featured_badge"] = ""

    if profile["featured_stat"] not in FEATURED_STATS:

        profile["featured_stat"] = ""

    return profile


def _db_get_profile(user_id):

    from data.DB.Storage.storage import get_profile

    try:

        row = run_coro_threadsafe(
            get_profile(str(user_id))
        ).result(timeout=10)

    except Exception:

        return {}

    if not row:

        return {}

    # Drop DB-only columns before cleaning.
    row = {
        k: v
        for k, v in row.items()
        if k in DEFAULT_PROFILE
    }

    return _clean_profile(row)


def _db_save_profile(user_id, profile):

    from data.DB.Storage.storage import save_profile

    run_coro_threadsafe(
        save_profile(str(user_id), profile)
    ).result(timeout=10)


def _maybe_migrate_json():

    """One-time import of legacy data/profiles.json into SQLite.

    Runs once per process. Only imports users with no DB row yet,
    then renames the JSON file to a backup so it never runs twice.
    Failures are swallowed: profiles must never break on migration.
    """

    global _MIGRATION_DONE

    if _MIGRATION_DONE:

        return

    _MIGRATION_DONE = True

    if not os.path.exists(LEGACY_PROFILES_PATH):

        return

    try:

        with open(
            LEGACY_PROFILES_PATH,
            encoding="utf-8",
        ) as f:

            legacy = json.load(f)

        if not isinstance(legacy, dict):

            return

        for user_id, saved in legacy.items():

            try:

                if _db_raw_exists(user_id):

                    continue

                _db_save_profile(user_id, _clean_profile(saved))

            except Exception:

                continue

        os.replace(
            LEGACY_PROFILES_PATH,
            LEGACY_BACKUP_PATH,
        )

    except Exception:

        pass


def _db_raw_exists(user_id):

    from data.DB.Storage.storage import get_profile

    try:

        row = run_coro_threadsafe(
            get_profile(str(user_id))
        ).result(timeout=10)

    except Exception:

        return False

    return bool(row)


def _get_profile(user_id):

    _maybe_migrate_json()

    saved = _db_get_profile(user_id)

    if saved:

        return saved

    return dict(DEFAULT_PROFILE)


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
    member_since = None

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
            "best_guild_progress": None,
            "member_since": None,
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

        joined_at = None

        try:

            member = guild.get_member(int(user_id))

            if member is not None and member.joined_at is not None:

                joined_at = member.joined_at.isoformat()

                if member_since is None or joined_at < member_since:

                    member_since = joined_at

        except (ValueError, TypeError):

            pass

        xp_needed = level * 100
        progress_pct = min(
            (xp / xp_needed) * 100 if xp_needed else 0,
            100,
        )

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
            "joined_at": joined_at,
            "xp_needed": xp_needed,
            "progress_pct": round(progress_pct, 1),
        })

        total_xp += xp
        total_played += played
        total_points += points
        total_majority += majority
        best_level = max(best_level, level)
        best_streak = max(best_streak, daily_streak)
        best_game_streak = max(best_game_streak, game_streak)

    best_progress = None

    if per_guild:

        top = max(
            per_guild,
            key=lambda g: (g["level"], g["xp"]),
        )

        best_progress = {
            "guild_name": top["guild_name"],
            "level": top["level"],
            "xp": top["xp"],
            "xp_needed": top["xp_needed"],
            "progress_pct": top["progress_pct"],
            "rank": top["rank"],
        }

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
        "best_guild_progress": best_progress,
        "member_since": member_since,
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
# ACTIVITY FEED
# =========================================================

def get_user_activity(user_id, limit=20):

    from data.DB.Storage.storage import get_activity

    try:

        rows = run_coro_threadsafe(
            get_activity(str(user_id), limit)
        ).result(timeout=10)

    except Exception:

        return []

    return [
        {
            "kind": row.get("kind"),
            "detail": row.get("detail") or {},
            "ts": row.get("ts"),
        }
        for row in rows
    ]


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

    profile = _get_profile(user_id)

    return jsonify({

        "success": True,

        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "global_name": user.get("global_name"),
            "avatar": user.get("avatar"),
            "banner": user.get("banner"),
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

    tags = body.get("tags", [])

    if isinstance(tags, str):

        tags = [t.strip() for t in tags.split(",")]

    incoming = {
        "bio": body.get("bio", ""),
        "accent": body.get("accent", ""),
        "banner": body.get("banner", ""),
        "status": body.get("status", ""),
        "avatar_url": body.get("avatar_url", ""),
        "background_url": body.get("background_url", ""),
        "pronouns": body.get("pronouns", ""),
        "display_name": body.get("display_name", ""),
        "featured_badge": body.get("featured_badge", ""),
        "featured_stat": body.get("featured_stat", ""),
        "socials": body.get("socials", []),
        "tags": tags,
        "public": body.get("public", False),
    }

    profile = _clean_profile(incoming)

    try:

        _maybe_migrate_json()
        _db_save_profile(user_id, profile)

    except Exception as exc:

        print(
            "[Profiles API] Failed to save profile: "
            f"{exc}"
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
# SELF STATS + BADGES + ACTIVITY
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

        "activity": get_user_activity(user_id),

    })


# =========================================================
# PUBLIC PROFILE
# =========================================================

@profiles_api.get(
    "/profile/public/<user_id>"
)
def get_public_profile(user_id):

    profile = _get_profile(str(user_id))

    if not profile.get("public"):

        return jsonify({
            "success": False,
            "error": "Profile not found or not public.",
        }), 404

    # Display name + avatar/banner from the bot (shared servers only).
    display_name = None
    avatar_url = None
    banner_url = None
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

                if member_user.banner is not None:

                    banner_url = str(member_user.banner.url)

        except (ValueError, TypeError):

            pass

    stats = get_user_stats(user_id)

    # Public profiles never expose per-server details: guild names
    # would reveal which servers the user is in.
    public_stats = {
        "totals": stats["totals"],
        "best_guild_progress": stats["best_guild_progress"],
        "member_since": stats["member_since"],
        "bot_ready": stats["bot_ready"],
    }

    return jsonify({

        "success": True,

        "user": {
            "id": str(user_id),
            "display_name": display_name,
            "avatar_url": avatar_url,
            "banner_url": banner_url,
        },

        "profile": profile,

        "stats": public_stats,

        "badges": get_badges(stats),

        "activity": get_user_activity(user_id),

    })
