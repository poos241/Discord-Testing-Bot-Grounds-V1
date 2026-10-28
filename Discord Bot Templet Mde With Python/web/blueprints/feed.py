"""Community activity feed.

A global web feed built from the existing profile_activity table
(level-ups, daily claims, game rounds, badge awards) -- not just
each person's own last-20 on their profile page.

Privacy follows the public-profile rules exactly, same as the
member directory:
- Only activity from users whose profile has ``public`` set
  shows up at all. A private profile's activity never appears,
  even to a logged-in member.
- Each entry links to the author's public profile page, and
  shows only the display name + avatar (live Discord name/avatar
  first, saved profile values as fallback).
- No guild info is ever returned: guild_id is stripped from
  every entry, and no server list or per-guild stats are shown.

The page itself is login-gated, like the directory. No new
database table: profile_activity already exists, and the
storage helper filters it to public profiles only.
"""

from flask import (
    Blueprint,
    jsonify,
    render_template,
    request,
)

from web.blueprints.directory import _person
from web.security.decorators import require_login
from web.services.discord_state import run_coro_threadsafe


feed_api = Blueprint(
    "feed",
    __name__,
)


PAGE_SIZE = 30

KINDS = (
    "level_up",
    "daily_claim",
    "game_round",
    "badge_award",
)


def _feed_entry(row, profiles_by_id):
    """One activity row rendered for the feed, or None.

    The author must have a public profile (the storage helper
    already filters to those); the entry carries no guild info.
    """

    user_id = str(row.get("user_id", ""))

    if not user_id:
        return None

    profile = profiles_by_id.get(user_id) or {}
    person = _person(user_id, profile)

    return {
        "id": row.get("id"),
        "user_id": user_id,
        "display_name": person["display_name"],
        "avatar_url": person["avatar_url"],
        "profile_url": "/profile/" + user_id,
        "kind": row.get("kind"),
        "detail": row.get("detail") or {},
        "ts": row.get("ts"),
    }


@feed_api.get("/feed")
@require_login
def feed_page():
    return render_template("feed.html")


@feed_api.get("/api/feed")
@require_login
def feed_list():
    from data.DB.Storage.storage import (
        list_public_activity,
        list_public_profiles,
    )

    kind = (request.args.get("kind") or "").strip()
    if kind not in KINDS:
        kind = ""

    try:
        page = int(request.args.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    if page < 1:
        page = 1

    offset = (page - 1) * PAGE_SIZE

    try:
        profile_rows = run_coro_threadsafe(
            list_public_profiles()
        ).result(timeout=15)
        profiles_by_id = {
            str(r.get("user_id")): r
            for r in (profile_rows or [])
            if r.get("user_id")
        }
        # One extra row probes whether a next page exists.
        rows = run_coro_threadsafe(
            list_public_activity(
                limit=PAGE_SIZE + 1,
                offset=offset,
                kind=kind or None,
            )
        ).result(timeout=15)
    except Exception as exc:
        print("[Feed] Failed to load activity feed: %r" % (exc,))
        return jsonify({
            "success": False,
            "error": "Could not load the activity feed.",
            "entries": [],
            "page": page,
            "has_next": False,
            "has_prev": page > 1,
            "kind": kind,
        }), 500

    rows = rows or []
    has_next = len(rows) > PAGE_SIZE
    entries = []
    for row in rows[:PAGE_SIZE]:
        entry = _feed_entry(row, profiles_by_id)
        if entry is not None:
            entries.append(entry)

    return jsonify({
        "success": True,
        "entries": entries,
        "page": page,
        "has_next": has_next,
        "has_prev": page > 1,
        "kind": kind,
    })
