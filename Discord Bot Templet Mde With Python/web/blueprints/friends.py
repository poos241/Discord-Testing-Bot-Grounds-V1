"""Website friend system API.

Mutual friendships for the web profiles: one user sends a friend
request, the other accepts or declines it. Only an accepted request
is a friendship — there is no one-way follow.

Storage lives in two NEW tables in ``data/DB/models.py``
(``friendships`` + ``friend_settings``); no existing table is altered,
so ``create_all()`` creates them on the next bot boot. The opt-out
toggle lives in ``friend_settings``, not on the profiles row, for the
same reason: adding a profiles column would need a boot-time ALTER
TABLE migration, and the setting is friend-system state, not profile
content.

Privacy rules (same pattern as public profiles):
- Your own view (``GET /api/friends``) always shows everything: your
  friends, your pending incoming/outgoing requests, your setting.
- A public profile (``GET /api/friends/public/<user_id>``) lists only
  friends who are THEMSELVES public. A private user's friendship is
  never exposed through someone else's public page, and a non-public
  owner's friends are never listed at all.
- Every action checks the logged-in session user against the row it
  touches: you can only accept/decline requests sent TO you, cancel
  requests sent BY you, and unfriend your own friendships.

Notification bell: pending incoming requests are fed into
``web/blueprints/notifications.py`` as ``friend`` items, so a new
request shows up in the bell. Accept/decline from the bell posts to
``/api/friends/respond``. Dismissing a bell item only hides that item
(it is recorded in notification_read.json); the request itself stays
pending until it is accepted, declined, or the recipient turns the
opt-out on (which auto-declines pending incoming requests).

Sending a request also checks that the recipient shares a server with
the sender (via the bot's guild cache, falling back to a member fetch
in a shared guild). When the bot is not connected the check is
skipped rather than blocking the request — the recipient can always
decline.
"""

import secrets
import time

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from web.blueprints.auth import get_csrf_token
from web.security.decorators import require_login
from web.services.discord_state import discord_state, run_coro_threadsafe


friends_api = Blueprint(
    "friends",
    __name__,
    url_prefix="/api",
)


def _current_user_id():
    user = session.get("user") or {}
    return str(user.get("id", ""))


def _current_display_name():
    user = session.get("user") or {}
    return (
        user.get("global_name")
        or user.get("username")
        or ""
    )


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


def _json_body():
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def _person(user_id):
    """Display info for a user id: live Discord name/avatar first,
    then their saved profile display name, then a bare id fallback."""

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

    if not name or not avatar_url:
        try:
            from data.DB.Storage.storage import get_profile

            row = run_coro_threadsafe(
                get_profile(user_id)
            ).result(timeout=10)
        except Exception:
            row = {}
        if isinstance(row, dict):
            if not name:
                name = row.get("display_name") or ""
            if not avatar_url:
                avatar_url = row.get("avatar_url") or ""

    return {
        "user_id": user_id,
        "display_name": name or ("User " + user_id),
        "avatar_url": avatar_url,
    }


def _friend_entry(row, me):
    """A friendships row rendered for ``me``: the OTHER party plus
    the row id and timestamps."""

    other = (
        row["addressee_id"]
        if str(row["requester_id"]) == str(me)
        else row["requester_id"]
    )
    entry = _person(other)
    entry["request_id"] = row["id"]
    entry["since_ts"] = row.get("decided_ts") or row.get("created_ts")
    return entry


def _pending_entry(row, me):
    """A pending row rendered for ``me``: the other party, the row
    id, who sent it, and when."""

    other = (
        row["addressee_id"]
        if str(row["requester_id"]) == str(me)
        else row["requester_id"]
    )
    entry = _person(other)
    entry["request_id"] = row["id"]
    entry["created_ts"] = row.get("created_ts")
    entry["incoming"] = str(row["addressee_id"]) == str(me)
    # Stored at request time so the bell and pending lists can name
    # the sender even when the bot is not connected.
    if entry["incoming"] and row.get("requester_name"):
        entry["display_name"] = row["requester_name"]
    return entry


def _shares_server(sender_id, target_id):
    """True when sender and target share a bot guild.

    Cached members first; if the target is not cached, try a member
    fetch in a guild the sender is in (per their Discord guild list).
    When the bot is not connected, or a check errors unexpectedly,
    allow the request rather than blocking it — the recipient can
    always decline. A definitive not-found/forbidden fetch denies it.
    """

    bot = discord_state.bot
    if bot is None or not discord_state.ready:
        return True

    try:
        sender = int(sender_id)
        target = int(target_id)
    except (ValueError, TypeError):
        return False

    try:
        for guild in bot.guilds:
            if (
                guild.get_member(sender) is not None
                and guild.get_member(target) is not None
            ):
                return True
    except Exception:
        return True

    # Not cached: try a live member fetch in a shared guild.
    try:
        from web.blueprints.auth import get_user_guilds

        my_guilds = {
            str(g.get("id"))
            for g in (get_user_guilds() or [])
            if isinstance(g, dict)
        }
    except Exception:
        return True

    for guild in bot.guilds:
        if str(guild.id) not in my_guilds:
            continue
        if guild.get_member(sender) is None:
            continue
        try:
            member = run_coro_threadsafe(
                guild.fetch_member(target)
            ).result(timeout=10)
        except Exception as exc:
            # discord.NotFound / Forbidden mean "not a member here".
            name = type(exc).__name__
            if name in ("NotFound", "Forbidden"):
                continue
            return True
        if member is not None:
            return True
    return False


def _db(call, *args):
    """Run a storage coroutine on the bot loop, or raise."""

    return run_coro_threadsafe(call(*args)).result(timeout=15)


# =========================================================
# SELF VIEW
# =========================================================

@friends_api.get(
    "/friends"
)
@require_login
def get_friends():
    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    try:
        from data.DB.Storage.storage import (
            get_friend_settings,
            list_accepted_friends,
            list_incoming_pending_friends,
            list_outgoing_pending_friends,
        )

        settings = _db(get_friend_settings, me)
        accepted = _db(list_accepted_friends, me)
        incoming = _db(list_incoming_pending_friends, me)
        outgoing = _db(list_outgoing_pending_friends, me)
    except Exception as exc:
        print("[Friends API] Failed to load friends: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Friends are not available yet — restart the bot and try again.",
        }), 503

    return jsonify({
        "success": True,
        "friends": [_friend_entry(r, me) for r in accepted],
        "incoming": [_pending_entry(r, me) for r in incoming],
        "outgoing": [_pending_entry(r, me) for r in outgoing],
        "settings": {
            "allow_requests": bool(
                settings.get("allow_requests", True)
            ),
        },
    })


# =========================================================
# SEND / RESPOND / CANCEL / UNFRIEND
# =========================================================

@friends_api.post(
    "/friends/request"
)
@require_login
def send_request():
    denied = _check_csrf()
    if denied is not None:
        return denied

    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    target = str(_json_body().get("user_id") or "").strip()
    if not target.isdigit():
        return jsonify({
            "success": False,
            "error": "Enter a numeric Discord user ID.",
        }), 400
    if target == me:
        return jsonify({
            "success": False,
            "error": "You cannot send a friend request to yourself.",
        }), 400

    try:
        from data.DB.Storage.storage import (
            create_or_reopen_friend_request,
            get_friend_pair,
            get_friend_settings,
        )

        settings = _db(get_friend_settings, target)
        if settings and not settings.get("allow_requests", True):
            return jsonify({
                "success": False,
                "error": "This user is not accepting friend requests right now.",
            }), 403

        existing = _db(get_friend_pair, me, target)
        if existing and existing.get("status") in ("pending", "accepted"):
            return jsonify({
                "success": False,
                "error": (
                    "You are already friends."
                    if existing["status"] == "accepted"
                    else "There is already a pending friend request between you."
                ),
            }), 409

        if not _shares_server(me, target):
            return jsonify({
                "success": False,
                "error": "You can only send friend requests to people who share a server with you.",
            }), 403

        row = _db(
            create_or_reopen_friend_request,
            me, target, _current_display_name(), int(time.time()),
        )
    except Exception as exc:
        print("[Friends API] Failed to send request: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Could not send the friend request.",
        }), 500

    return jsonify({
        "success": True,
        "request_id": row.get("id"),
    })


@friends_api.post(
    "/friends/respond"
)
@require_login
def respond_request():
    denied = _check_csrf()
    if denied is not None:
        return denied

    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    body = _json_body()
    try:
        request_id = int(body.get("request_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Missing friend request.",
        }), 400
    action = str(body.get("action") or "")
    if action not in ("accept", "decline"):
        return jsonify({
            "success": False,
            "error": "Action must be 'accept' or 'decline'.",
        }), 400

    try:
        from data.DB.Storage.storage import (
            get_friend_request,
            update_friend_request,
        )

        row = _db(get_friend_request, request_id)
        if (
            not row
            or row.get("status") != "pending"
            or str(row.get("addressee_id")) != me
        ):
            return jsonify({
                "success": False,
                "error": "Friend request not found.",
            }), 404

        _db(
            update_friend_request,
            request_id,
            "accepted" if action == "accept" else "declined",
            int(time.time()),
        )
    except Exception as exc:
        print("[Friends API] Failed to respond: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Could not update the friend request.",
        }), 500

    return jsonify({
        "success": True,
        "status": "accepted" if action == "accept" else "declined",
    })


@friends_api.post(
    "/friends/cancel"
)
@require_login
def cancel_request():
    denied = _check_csrf()
    if denied is not None:
        return denied

    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    body = _json_body()
    try:
        request_id = int(body.get("request_id"))
    except (TypeError, ValueError):
        return jsonify({
            "success": False,
            "error": "Missing friend request.",
        }), 400

    try:
        from data.DB.Storage.storage import (
            delete_friend_request,
            get_friend_request,
        )

        row = _db(get_friend_request, request_id)
        if (
            not row
            or row.get("status") != "pending"
            or str(row.get("requester_id")) != me
        ):
            return jsonify({
                "success": False,
                "error": "Friend request not found.",
            }), 404

        _db(delete_friend_request, request_id)
    except Exception as exc:
        print("[Friends API] Failed to cancel: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Could not cancel the friend request.",
        }), 500

    return jsonify({"success": True})


@friends_api.post(
    "/friends/unfriend"
)
@require_login
def unfriend():
    denied = _check_csrf()
    if denied is not None:
        return denied

    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    target = str(_json_body().get("user_id") or "").strip()
    if not target.isdigit() or target == me:
        return jsonify({
            "success": False,
            "error": "Invalid user.",
        }), 400

    try:
        from data.DB.Storage.storage import (
            delete_friend_request,
            get_friend_pair,
        )

        row = _db(get_friend_pair, me, target)
        if not row or row.get("status") != "accepted":
            return jsonify({
                "success": False,
                "error": "You are not friends with this user.",
            }), 404

        _db(delete_friend_request, row["id"])
    except Exception as exc:
        print("[Friends API] Failed to unfriend: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Could not unfriend.",
        }), 500

    return jsonify({"success": True})


# =========================================================
# SETTINGS (opt-out toggle)
# =========================================================

@friends_api.get(
    "/friends/settings"
)
@require_login
def get_settings():
    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    try:
        from data.DB.Storage.storage import get_friend_settings

        settings = _db(get_friend_settings, me)
    except Exception as exc:
        print("[Friends API] Failed to load settings: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Friends are not available yet — restart the bot and try again.",
        }), 503

    return jsonify({
        "success": True,
        "allow_requests": bool(settings.get("allow_requests", True)),
    })


@friends_api.post(
    "/friends/settings"
)
@require_login
def save_settings():
    denied = _check_csrf()
    if denied is not None:
        return denied

    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    # Only a real JSON true counts as "allow"; anything else means
    # "do not send me friend requests" (same rule as the
    # notifications mark endpoint: never bool() a raw value).
    allow = _json_body().get("allow_requests") is True

    try:
        from data.DB.Storage.storage import (
            decline_pending_for_user,
            save_friend_settings,
        )

        _db(save_friend_settings, me, allow)
        declined = 0
        if not allow:
            # Turning the opt-out ON auto-declines requests already
            # waiting, so the toggle fully stops requests instead of
            # leaving a queue the user still has to clear. Turning it
            # back off later does not resurrect them; people can
            # simply send a new request. Outgoing requests the user
            # sent are untouched — the toggle is about receiving.
            declined = _db(decline_pending_for_user, me, int(time.time()))
    except Exception as exc:
        print("[Friends API] Failed to save settings: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Could not save friend settings.",
        }), 500

    return jsonify({
        "success": True,
        "allow_requests": allow,
        "declined_pending": declined,
    })


# =========================================================
# RELATIONSHIP STATUS (for another user's public profile page)
# =========================================================

@friends_api.get(
    "/friends/status/<user_id>"
)
@require_login
def get_status(user_id):
    me = _current_user_id()
    if not me:
        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    target = str(user_id)
    if target == me:
        return jsonify({
            "success": True,
            "status": "self",
            "allow_requests": True,
        })

    try:
        from data.DB.Storage.storage import (
            get_friend_pair,
            get_friend_settings,
        )

        row = _db(get_friend_pair, me, target)
        settings = _db(get_friend_settings, target)
    except Exception as exc:
        print("[Friends API] Failed to load status: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Friends are not available yet — restart the bot and try again.",
        }), 503

    status = "none"
    request_id = None
    if row and row.get("status") == "accepted":
        status = "friends"
    elif row and row.get("status") == "pending":
        if str(row.get("addressee_id")) == me:
            status = "pending_incoming"
        else:
            status = "pending_outgoing"
        request_id = row["id"]

    return jsonify({
        "success": True,
        "status": status,
        "request_id": request_id,
        # The target's own opt-out preference, shown only as the
        # reason the Add button is disabled — never their settings.
        "allow_requests": bool(settings.get("allow_requests", True)),
    })


# =========================================================
# PUBLIC FRIENDS (for another user's public profile page)
# =========================================================

@friends_api.get(
    "/friends/public/<user_id>"
)
def get_public_friends(user_id):
    user_id = str(user_id)

    try:
        from data.DB.Storage.storage import (
            get_profile,
            list_accepted_friends,
        )

        owner = _db(get_profile, user_id)
        if not owner or not owner.get("public"):
            return jsonify({
                "success": False,
                "error": "Profile not found or not public.",
            }), 404

        accepted = _db(list_accepted_friends, user_id)
        friends = []
        for row in accepted:
            other = (
                row["addressee_id"]
                if str(row["requester_id"]) == user_id
                else row["requester_id"]
            )
            # Mutual-public rule: only friends who are themselves
            # public appear here. Never leak a private user's
            # friendship through someone else's public page.
            friend_profile = _db(get_profile, str(other))
            if not friend_profile or not friend_profile.get("public"):
                continue
            entry = _person(other)
            entry["since_ts"] = row.get("decided_ts") or row.get("created_ts")
            friends.append(entry)
    except Exception as exc:
        print("[Friends API] Failed to load public friends: %s" % exc)
        return jsonify({
            "success": False,
            "error": "Friends are not available yet — restart the bot and try again.",
        }), 503

    return jsonify({
        "success": True,
        "friends": friends,
    })
