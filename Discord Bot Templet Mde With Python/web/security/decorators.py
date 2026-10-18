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


def require_permission(
    permission
):

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

            # We'll connect this to
            # PermissionService next.

            return func(
                *args,
                **kwargs
            )

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
