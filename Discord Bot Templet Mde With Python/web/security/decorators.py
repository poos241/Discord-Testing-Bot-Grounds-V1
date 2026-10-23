from functools import wraps

from flask import (
    abort,
    session,
)


def require_login(func):

    @wraps(func)
    def wrapper(
        *args,
        **kwargs
    ):

        if not session.get(
            "user"
        ):

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

        if not session.get(
            "user"
        ):

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

            if not session.get(
                "user"
            ):

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

            if not session.get("user"):
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


def require_guild_access(func):
    """Require Discord login, plus Manage Server on the target guild.

    The guild ID is read from URL params, query args, or JSON body (in
    that order). Routes without any guild ID just require login.
    """

    @wraps(func)
    def wrapper(*args, **kwargs):
        from flask import jsonify, request
        from web.blueprints.auth import user_can_manage_guild

        if not session.get("user"):
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
