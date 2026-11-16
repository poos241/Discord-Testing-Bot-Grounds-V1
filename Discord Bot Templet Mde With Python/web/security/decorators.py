from functools import wraps

from flask import (
    abort,
    session,
)


def _session_alive():
    """True when the browser cookie session matches a live server-side
    auth session.

    Login state is split in two: the Flask cookie carries ``user`` /
    ``auth_sid`` and survives a kushweb restart, while the OAuth data
    and the CSRF token live in the in-memory ``_AUTH_SESSIONS`` dict,
    which a restart wipes. A cookie that outlived its server-side
    session is a stale half-login: the gates used to pass it (owner
    bypass reads the cookie user id), and the first POST then failed
    with a confusing "Invalid CSRF token" because the expected token
    was gone. Treat the stale state as logged out instead, and drop
    the stale cookie data so the next step is a clean login.
    """
    if not session.get("user"):
        return False
    from web.blueprints.auth import get_auth_session

    if get_auth_session() is None:
        session.clear()
        return False
    return True


def require_login(func):

    @wraps(func)
    def wrapper(
        *args,
        **kwargs
    ):

        if not _session_alive():

            abort(401)

        return func(
            *args,
            **kwargs
        )

    return wrapper


def require_guild_manage(func):
    """Require login AND Manage Server / Administrator on the guild.

    Reads the guild id from the ``guild_id`` (or ``gid``) view argument
    and aborts 403 when the logged-in user cannot manage that guild.
    """

    @wraps(func)
    def wrapper(
        *args,
        **kwargs
    ):

        if not _session_alive():

            abort(401)

        guild_id = kwargs.get(
            "guild_id",
            kwargs.get("gid")
        )

        if guild_id is None:

            abort(400)

        # Lazy import: web.blueprints.auth must not import this module
        # at load time (circular import).
        from web.blueprints.auth import user_can_manage_guild

        if not user_can_manage_guild(
            guild_id
        ):

            abort(403)

        return func(
            *args,
            **kwargs
        )

    return wrapper


def _request_guild_id():
    """Read the target guild id from view args, query args, or JSON body."""
    from flask import request

    guild_id = None
    if request.view_args:
        guild_id = request.view_args.get(
            "guild_id",
            request.view_args.get("gid")
        )
    if guild_id is None:
        guild_id = request.args.get(
            "guild_id",
            request.args.get("gid")
        )
    if guild_id is None and request.is_json:
        try:
            guild_id = (
                request.get_json(silent=True) or {}
            ).get("guild_id")
        except Exception:
            pass
    return guild_id


def require_permission(
    level
):
    """Page-style gate: abort 401/403 unless the user meets the access level.

    ``level`` is one of "viewer", "moderator", "admin".
    Connected to web.services.permissions.PermissionService.
    """

    def decorator(func):

        @wraps(func)
        def wrapper(
            *args,
            **kwargs
        ):

            if not _session_alive():

                abort(401)

            from web.services.permissions import (
                has_access,
            )

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(
                    *args,
                    **kwargs
                )

            if not has_access(
                guild_id,
                level
            ):

                abort(403)

            return func(
                *args,
                **kwargs
            )

        return wrapper

    return decorator


def _api_guild_gate(level):
    """Shared logic for the JSON API guild decorators below."""

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import jsonify

            from web.services.permissions import (
                has_access,
            )

            if not _session_alive():
                return jsonify({
                    "success": False,
                    "error": "Authentication required.",
                }), 401

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(*args, **kwargs)

            if not has_access(guild_id, level):
                messages = {
                    "viewer": "You must be a member of this server.",
                    "moderator": "Moderator permissions required.",
                    "admin": "No permission for this server.",
                }
                return jsonify({
                    "success": False,
                    "error": messages.get(
                        level,
                        "No permission for this server."
                    ),
                }), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_guild_member(func):
    """API gate: login + guild membership (viewer tier or higher)."""
    return _api_guild_gate("viewer")(func)


def require_guild_moderator(func):
    """API gate: login + moderator tier or higher on the guild."""
    return _api_guild_gate("moderator")(func)


def require_guild_permission(*flags, label=None):
    """API gate: login + one of the given Discord permission bits on the
    guild (administrators and the guild owner always pass). Use instead
    of the coarse moderator tier when an action maps to a specific
    Discord permission: ban needs Ban Members, timeout needs Timeout
    Members, rename needs Manage Nicknames, and so on."""

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import jsonify

            from web.services.permissions import (
                has_guild_permission,
            )

            if not _session_alive():
                return jsonify({
                    "success": False,
                    "error": "Authentication required.",
                }), 401

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(*args, **kwargs)

            if not has_guild_permission(guild_id, *flags):
                return jsonify({
                    "success": False,
                    "error": label or "You don't have permission to do that in this server.",
                }), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_guild_access(func):
    """Require Discord login, plus Manage Server on the target guild.

    The guild ID is read from URL params, query args, or JSON body (in
    that order). Routes without any guild ID just require login.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from flask import jsonify, request
        from web.blueprints.auth import user_can_manage_guild

        if not _session_alive():
            return jsonify({"success": False, "error": "Authentication required."}), 401

        guild_id = None
        if request.view_args:
            guild_id = request.view_args.get("guild_id") or request.view_args.get("gid")
        if guild_id is None:
            guild_id = request.args.get("guild_id") or request.args.get("gid")
        if guild_id is None and request.is_json:
            try:
                guild_id = (request.get_json(silent=True) or {}).get("guild_id")
            except Exception:
                pass
        if guild_id is not None and not user_can_manage_guild(guild_id):
            return jsonify({"success": False, "error": "No permission for this server."}), 403

        return func(*args, **kwargs)

    return wrapper


# ============================================================
# WEB PERMISSION SYSTEM (2026-11-15)
#
# Page and API gates backed by the bot's command_permissions rules
# (web/services/web_access.py). Check order, for both gates:
#   (a) login,
#   (b) owner bypass (Emily or the guild owner) -> allow,
#   (c) unverified (member holds the guild's unverified role, or the
#       user is not a member at all) -> blocked,
#   (d) the requested action is not granted -> blocked.
# The unverified flag is re-checked fresh on every call; the
# permission booleans may come from the 5-minute session cache.
# When the bot is unreachable the gate fails closed ("unavailable" /
# 503) instead of letting anyone in.
# ============================================================

_BLOCKED_MESSAGES = {
    "not_member": "You're not a member of this server.",
    "unverified": "Complete the captcha in Discord first.",
    "permission": "You don't have permission to access this server's dashboard.",
    "unavailable": "The bot is unreachable right now -- try again in a bit.",
}


def _web_block_reason(guild_id, action):
    """None when the session user may do ``action`` in the guild,
    else the block reason. "unavailable" when the bot is down."""
    from web.services.bridge import BridgeUnavailable
    from web.services.web_access import check_web_access

    try:
        return check_web_access(guild_id, action)
    except BridgeUnavailable:
        return "unavailable"
    except Exception:
        return "unavailable"


def require_web_access(action):
    """Page-style gate: login + web permission ``action`` on the guild.

    Blocked page routes redirect to "/?blocked=<gid>&reason=<reason>"
    so the landing page can explain which server and why. Routes
    without a guild id in the request just require login (same as
    the old require_permission behaviour).
    """

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import redirect, url_for

            if not _session_alive():
                return redirect(url_for("auth.login"))

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(*args, **kwargs)

            reason = _web_block_reason(guild_id, action)
            if reason is not None:
                return redirect(
                    url_for(
                        "home",
                        blocked=str(guild_id),
                        reason=reason,
                    )
                )

            return func(*args, **kwargs)

        return wrapper

    return decorator


def require_web_access_any(*actions):
    """Page-style gate: login + ANY of the web permissions ``actions``.

    Used by pages that merge two gated areas (the combined
    Permissions + Logger Settings page). Blocked routes redirect to
    "/?blocked=<gid>&reason=<reason>" like require_web_access; the
    reason comes from the first action that blocks (the reasons are
    action-independent except the final permission check, which
    yields the same string for every action).
    """

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import redirect, url_for

            if not _session_alive():
                return redirect(url_for("auth.login"))

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(*args, **kwargs)

            reasons = [_web_block_reason(guild_id, a) for a in actions]
            if any(r is None for r in reasons):
                return func(*args, **kwargs)

            reason = next((r for r in reasons if r is not None), "permission")
            return redirect(
                url_for(
                    "home",
                    blocked=str(guild_id),
                    reason=reason,
                )
            )

        return wrapper

    return decorator


def require_web_api_access(action):
    """JSON API gate: login + web permission ``action`` on the guild.

    Answers 401 when logged out, 503 when the bot is unreachable,
    and 403 with a clear error for not-a-member / unverified /
    no-permission. Routes without a guild id just require login.
    """

    def decorator(func):

        @wraps(func)
        def wrapper(*args, **kwargs):
            from flask import jsonify

            if not _session_alive():
                return jsonify({
                    "success": False,
                    "error": "Authentication required.",
                }), 401

            guild_id = _request_guild_id()

            # No guild in the request: login alone is enough.
            if guild_id is None:
                return func(*args, **kwargs)

            reason = _web_block_reason(guild_id, action)
            if reason == "unavailable":
                return jsonify({
                    "success": False,
                    "error": "Discord bot is not connected.",
                }), 503
            if reason is not None:
                return jsonify({
                    "success": False,
                    "error": _BLOCKED_MESSAGES.get(
                        reason,
                        "No permission for this server.",
                    ),
                }), 403

            return func(*args, **kwargs)

        return wrapper

    return decorator
