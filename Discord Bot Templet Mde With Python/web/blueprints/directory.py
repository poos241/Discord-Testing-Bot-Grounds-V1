"""Member directory by interest tag.

A web page where logged-in members can browse each other by the
interest tags stored on profiles (up to 10 per profile, see
web/blueprints/profiles.py).

Privacy follows the public-profile rules exactly:
- Only profiles with ``public`` set show up at all. A private
  profile is never listed, even to a logged-in member.
- Each entry shows only what a public profile is allowed to show:
  display name, avatar, pronouns, bio, status, socials, tags,
  totals-only stats, and earned badges. No server list, no
  per-guild stats, and no roles are ever included.
- Timezone / location / country show only when the owner opted
  in with ``show_local_info`` (same strip rule as the public
  profile page); otherwise they are removed from the entry.
- No new database table: tags already live on the ``profiles``
  table, and this blueprint only reads rows where ``public``
  is true (see ``list_public_profiles`` in storage).

Filtering: ``?tag=X&tag=Y`` keeps only members who have ALL of
the given tags (AND), matched case-insensitively. ``?search=``
matches a substring of the display name, bio, status, or tags.
"""

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)

from web.blueprints.profiles import (
    DEFAULT_PROFILE,
    _clean_profile,
    get_badges,
    get_custom_badges,
    get_user_stats,
)
from web.security.decorators import require_login
from web.services.discord_state import discord_state, run_coro_threadsafe


directory_api = Blueprint(
    "directory",
    __name__,
)


MAX_MEMBERS = 200


def _person(user_id, profile):
    """Display name + avatar for a user id, bot cache first.

    Same fallback order as the friends blueprint: live Discord
    name/avatar, then the saved profile display name / avatar
    URL, then a bare id fallback. No guild info is ever used,
    so this cannot leak which servers the person is in.
    """

    user_id = str(user_id)
    name = ""
    avatar_url = ""

    bot = discord_state.bot

    if bot is not None and discord_state.ready:
        try:
            member_user = bot.get_user(int(user_id))
            if member_user is not None:
                name = member_user.global_name or member_user.name
                avatar_url = str(member_user.display_avatar.url)
        except (ValueError, TypeError):
            pass

    if not name:
        name = profile.get("display_name") or ""
    if not avatar_url:
        avatar_url = profile.get("avatar_url") or ""

    return {
        "user_id": user_id,
        "display_name": name or ("User " + user_id),
        "avatar_url": avatar_url,
    }


def _directory_entry(row):
    """One public profile rendered for the directory, or None."""

    user_id = str(row.get("user_id", ""))

    if not user_id:
        return None

    saved = {
        k: v
        for k, v in row.items()
        if k in DEFAULT_PROFILE
    }
    profile = _clean_profile(saved)

    if not profile.get("public"):
        return None

    entry = _person(user_id, profile)

    entry["pronouns"] = profile.get("pronouns", "")
    entry["bio"] = profile.get("bio", "")
    entry["status"] = profile.get("status", "")
    entry["socials"] = profile.get("socials", [])
    entry["tags"] = profile.get("tags", [])
    entry["dm_status"] = profile.get("dm_status", "")

    # Local info only when the owner opted in; otherwise strip
    # it, exactly as the public profile page does.
    if profile.get("show_local_info"):
        entry["timezone"] = profile.get("timezone", "")
        entry["location"] = profile.get("location", "")
        entry["country"] = profile.get("country", "")
    else:
        entry["timezone"] = ""
        entry["location"] = ""
        entry["country"] = ""

    # Totals only: per-guild stats would reveal server membership.
    try:
        stats = get_user_stats(user_id)
        totals = stats.get("totals", {})
        badges = [
            b for b in (get_badges(stats) + get_custom_badges(user_id))
            if b.get("earned")
        ]
    except Exception:
        totals = {
            "xp": 0,
            "level": 0,
            "played": 0,
            "points": 0,
            "daily_streak": 0,
        }
        badges = []

    entry["stats"] = {
        "level": totals.get("level", 0),
        "xp": totals.get("xp", 0),
        "played": totals.get("played", 0),
        "points": totals.get("points", 0),
        "daily_streak": totals.get("daily_streak", 0),
    }
    entry["badges"] = badges
    entry["profile_url"] = "/profile/" + user_id

    return entry


def _tag_cloud(entries):
    """[{tag, count}] over all directory entries, most used first.

    Tags group case-insensitively; the displayed spelling is the
    most common casing seen for that tag.
    """

    grouped = {}

    for entry in entries:
        for tag in entry.get("tags", []):
            key = tag.lower()
            bucket = grouped.setdefault(
                key, {"tag": tag, "count": 0, "spellings": {}}
            )
            bucket["count"] += 1
            bucket["spellings"][tag] = bucket["spellings"].get(tag, 0) + 1

    cloud = []
    for bucket in grouped.values():
        display = max(
            bucket["spellings"].items(),
            key=lambda kv: kv[1],
        )[0]
        cloud.append({"tag": display, "count": bucket["count"]})

    cloud.sort(key=lambda t: (-t["count"], t["tag"].lower()))
    return cloud


@directory_api.get("/directory")
@require_login
def directory_page():
    return render_template("directory.html")


@directory_api.get("/api/directory")
@require_login
def directory_list():
    from data.DB.Storage.storage import list_public_profiles

    try:
        rows = run_coro_threadsafe(
            list_public_profiles()
        ).result(timeout=15)
    except Exception as exc:
        print("[Directory] Failed to list public profiles: %r" % (exc,))
        return jsonify({
            "success": False,
            "error": "Could not load the directory.",
            "members": [],
            "tags": [],
        }), 500

    entries = []
    for row in rows or []:
        entry = _directory_entry(row)
        if entry is not None:
            entries.append(entry)

    tags = _tag_cloud(entries)

    wanted = [
        t.strip().lower()
        for t in request.args.getlist("tag")
        if t.strip()
    ]
    search = (request.args.get("search") or "").strip().lower()

    def matches(entry):
        if wanted:
            mine = {t.lower() for t in entry.get("tags", [])}
            if not all(t in mine for t in wanted):
                return False
        if search:
            haystack = " ".join([
                entry.get("display_name", ""),
                entry.get("bio", ""),
                entry.get("status", ""),
                " ".join(entry.get("tags", [])),
            ]).lower()
            if search not in haystack:
                return False
        return True

    members = [e for e in entries if matches(e)]
    members.sort(key=lambda e: e["display_name"].lower())

    return jsonify({
        "success": True,
        "members": members[:MAX_MEMBERS],
        "total": len(members),
        "truncated": len(members) > MAX_MEMBERS,
        "tags": tags,
        "selected_tags": wanted,
    })
