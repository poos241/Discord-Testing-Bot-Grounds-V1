import os
import sys
import threading

from pathlib import Path


# ============================================================
# PROJECT ROOT
# ============================================================

ROOT_DIR = Path(__file__).resolve().parent.parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


# ============================================================
# FLASK
# ============================================================

from flask import (Flask, render_template, redirect, url_for, session, request,)


# ============================================================
# BLUEPRINTS
# ============================================================

from web.blueprints.api import api
from web.blueprints.members import members_api
from web.blueprints.server import servers_api


from web.blueprints.statistics import statistics_api

from web.blueprints.moderation import moderation_api
from web.blueprints.modpanel import modpanel_api
from web.blueprints.debug import debug_api, init_request_logging, init_panel_injection
from web.blueprints.leaderboard import leaderboard_api

from web.blueprints.events import events_api

from web.blueprints.health import health_api

from web.blueprints.channels import channels_api

from web.blueprints.voice import voice_api

from web.blueprints.member_stats import member_stats_api

from web.blueprints.explorer import explorer_api

from web.blueprints.channel_details import channel_details_api

from web.blueprints.server_overview import server_overview_api

from web.blueprints.event_stats import event_stats_api

from web.blueprints.search import search_api

from web.blueprints.member_details import member_details_api

from web.blueprints.role_details import role_details_api

from web.blueprints.auth import auth_api

from web.config import SECRET_KEY

from web.security.decorators import require_web_access, require_web_access_any

from web.blueprints.roles import roles_api
from web.blueprints.profiles import profiles_api
from web.blueprints.notifications import notifications_api
from web.blueprints.friends import friends_api
from web.blueprints.directory import directory_api
from web.blueprints.feed import feed_api
from web.blueprints.backups import backups_api
from web.blueprints.server_home import server_home_api

from web.blueprints.logger import logger_api
from web.blueprints.dashboard import dashboard_api
from web.blueprints.permissions import permissions_api

from web.services.discord_state import discord_state

# from web.blueprints.channels import channels_api
# from web.blueprints.roles import roles_api


# ============================================================
# CREATE APP
# ============================================================

def create_app(bot=None):

    # Windows registry maps .js to text/plain, which makes browsers refuse
    # to execute our scripts. Force the correct MIME types.
    import mimetypes
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")

    app = Flask(
        __name__, template_folder="templates", static_folder="static")

    app.config["SECRET_KEY"] = SECRET_KEY

    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    # Local development uses HTTP. Set WEB_COOKIE_SECURE=1 when behind HTTPS.
    app.config["SESSION_COOKIE_SECURE"] = (
        os.environ.get("WEB_COOKIE_SECURE", "").lower() in ("1", "true", "yes")
    )

    # Store the (always None, post-split) bot reference inside Flask
    # config for any legacy reader. The website holds no live bot.
    app.config["BOT"] = bot
    app.config["DISCORD_BOT"] = bot

    # Hand the bot reference to the discord_state shim used by
    # blueprints/services. Post-split this is always None: set_bot
    # discards any live object and the shim answers from the bridge.
    discord_state.set_bot(bot)

    # Upload cap: must match MAX_UPLOAD_BYTES (5 MB) in
    # web/blueprints/profiles.py and the "Max 5 MB" text on the edit
    # page. Flask rejects anything over this with a generic 413 before
    # the route's own check ever runs, so a lower cap here used to kill
    # 2-5 MB background uploads the site advertises as allowed.
    app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

    @app.context_processor
    def inject_security_helpers():
        from web.blueprints.auth import get_csrf_token
        from web.services.permissions import (
            get_access_level,
            has_access,
        )
        from web.services.web_access import web_can as _web_can

        def can(level, guild_id=None):
            gid = guild_id or session.get("selected_guild_id")
            if not gid:
                return False
            return has_access(gid, level)

        def selected_guild_level():
            gid = session.get("selected_guild_id")
            if not gid:
                return "none"
            return get_access_level(gid) or "none"

        def can_any(level):
            """True when the user meets the level on at least one guild."""
            from web.blueprints.auth import get_user_guilds

            for guild in get_user_guilds():
                if has_access(guild.get("id"), level):
                    return True
            return False

        def web_can(action, guild_id=None):
            """Template helper: True when the session user holds the
            web permission ``action`` in the guild (defaults to the
            selected guild). Used to hide buttons the API would
            reject. Fail closed."""
            return _web_can(action, guild_id)

        return {
            "csrf_token": get_csrf_token,
            "can": can,
            "can_any": can_any,
            "selected_guild_level": selected_guild_level,
            "web_can": web_can,
        }

    @app.errorhandler(403)
    def forbidden(_error):
        return render_template(
            "403.html",
            guild_id=session.get("selected_guild_id"),
        ), 403

    @app.after_request
    def add_security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        return response


    # ========================================================
    # API BLUEPRINTS
    # ========================================================

    
    app.register_blueprint(api,url_prefix="/api")
    
    app.register_blueprint(members_api  )


    app.register_blueprint(statistics_api)
    
    app.register_blueprint(moderation_api)
    app.register_blueprint(modpanel_api)
    app.register_blueprint(debug_api)
    init_request_logging(app)
    init_panel_injection(app)
    app.register_blueprint(leaderboard_api)
           
    app.register_blueprint(events_api)
    
    app.register_blueprint(logger_api)
    app.register_blueprint(dashboard_api)
    app.register_blueprint(permissions_api)
    
    app.register_blueprint(servers_api)
    
    app.register_blueprint(health_api)
    
    app.register_blueprint(channels_api)

    app.register_blueprint(voice_api)
    
    app.register_blueprint(member_stats_api)
    
    app.register_blueprint(explorer_api)
    
    app.register_blueprint(channel_details_api)
    
    app.register_blueprint(server_overview_api)
    
    app.register_blueprint(event_stats_api)
    
    app.register_blueprint(search_api)
    
    app.register_blueprint(member_details_api)
    
    app.register_blueprint(role_details_api)
    
    app.register_blueprint(roles_api)
    app.register_blueprint(profiles_api)
    app.register_blueprint(notifications_api)
    app.register_blueprint(friends_api)
    app.register_blueprint(directory_api)
    app.register_blueprint(feed_api)
    app.register_blueprint(backups_api)
    app.register_blueprint(server_home_api)
    
    app.register_blueprint(auth_api)
    
    

    # ========================================================
    # HOME HELPERS (web permission system)
    # ========================================================

    def _home_guild_name(guild_id):
        """Display name for a blocked guild id, or the id itself."""
        try:
            from web.blueprints.auth import get_user_guilds

            for guild in get_user_guilds() or []:
                if str(guild.get("id")) == str(guild_id):
                    return guild.get("name") or str(guild_id)
        except Exception:
            pass
        try:
            from web.services import bridge

            guild = bridge.get_guild(int(guild_id))
            if guild:
                return guild.get("name") or str(guild_id)
        except Exception:
            pass
        return str(guild_id)

    def _user_blocked_guilds():
        """[{id, name, reason}] for every guild the bot is in that
        the logged-in user is a member of but cannot enter.

        The reason is the fresh gate answer for that guild --
        "unverified" (still holds the captcha role), "permission"
        (verified member without dashboard access), "not_member", or
        "unavailable" (bot unreachable). Used by the no-access
        landing page so the user (and Emily) can tell a captcha
        block apart from a permission block instead of seeing one
        generic "locked" message. Returns [] when the bot is
        unreachable, matching _user_can_enter_any_guild's fallback
        of sending the user to the server list.
        """
        try:
            from web.blueprints.auth import get_user_guilds
            from web.services import bridge
            from web.services.web_access import can_enter_guild

            if not bridge.bot_is_ready():
                return []
            my_guilds = {
                str(g.get("id")): g
                for g in (get_user_guilds() or [])
            }
            blocked = []
            for gid in bridge.get_bot_guild_ids():
                gid = str(gid)
                if gid not in my_guilds:
                    continue
                can_enter, reason = can_enter_guild(gid)
                if not can_enter:
                    blocked.append({
                        "id": gid,
                        "name": (
                            my_guilds[gid].get("name") or gid
                        ),
                        "reason": reason or "permission",
                    })
            return blocked
        except Exception:
            return []

    def _user_can_enter_any_guild():
        """True when the logged-in user can enter at least one guild
        the bot is in. When the bot is unreachable, say True (fall
        back to the old behaviour: send them to the server list,
        which shows its own 503) instead of wrongly claiming they
        have no access anywhere."""
        try:
            from web.blueprints.auth import get_user_guilds
            from web.services import bridge
            from web.services.web_access import can_enter_guild

            if not bridge.bot_is_ready():
                return True
            my_guild_ids = {
                str(g.get("id")) for g in (get_user_guilds() or [])
            }
            for gid in bridge.get_bot_guild_ids():
                if str(gid) not in my_guild_ids:
                    continue
                can_enter, _reason = can_enter_guild(gid)
                if can_enter:
                    return True
            return False
        except Exception:
            return True


# ========================================================
# HOME
# ========================================================

    @app.route("/")
    def home():

        # Logged-in users go to the server list -- unless they were
        # blocked from a guild page, or they cannot enter any guild
        # at all, in which case the landing page itself explains why
        # (which server, and what to do about it).
        if session.get("user"):

            blocked_gid = request.args.get("blocked")
            reason = request.args.get("reason")
            if blocked_gid:
                return render_template(
                    "home.html",
                    blocked_guild_id=str(blocked_gid),
                    blocked_guild_name=_home_guild_name(blocked_gid),
                    blocked_reason=reason or "permission",
                )

            if _user_can_enter_any_guild():
                return redirect(
                    url_for("servers")
                )

            return render_template(
                "home.html",
                blocked_reason="no_access",
                blocked_guilds=_user_blocked_guilds(),
            )

        # Visitors get the public landing page.
        return render_template(
            "home.html"
        )


# ========================================================
# DASHBOARD ENTRY
# ========================================================

    @app.get("/dashboard")
    def dashboard():

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        guild_id = request.args.get(
            "guild_id",
            type=int
        )

        # No server selected.
        if not guild_id:

            return redirect(
                url_for("servers")
            )

        # Convert the old dashboard URL into
        # the new canonical server dashboard URL.
        return redirect(
            url_for(
                "server_dashboard",
                guild_id=guild_id
            )
        )


# ========================================================
# SERVER DASHBOARD
# ========================================================

    @app.get("/servers/<int:guild_id>/dashboard")
    @require_web_access("web:view_dashboard")
    def server_dashboard(guild_id):

        # Remember the server for this login session.
        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "dashboard.html",
            guild_id=guild_id
        )

    @app.route("/servers")
    def servers():

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        # A user who cannot enter ANY guild must never reach the
        # server select screen: the login flow (OAuth callback ->
        # /dashboard -> /servers) used to send them straight here,
        # so an unverified alt saw a page of locked cards instead
        # of the landing page explaining why. Send them home --
        # the home route renders the no-access landing with the
        # per-server reason.
        if not _user_can_enter_any_guild():
            return redirect(
                url_for("home")
            )

        return render_template(
            "servers.html"
        )


    @app.route("/profile")
    def profile():

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        return render_template(
            "profile.html",
            user=session.get("user"),
        )


    @app.route("/profile/edit")
    def profile_edit():

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        return render_template(
            "profile_edit.html",
            user=session.get("user"),
        )


    @app.route("/profile/<user_id>")
    def public_profile_page(user_id):

        # Data loads client-side from /api/profile/public/<user_id>;
        # private or missing profiles show a locked message.
        return render_template(
            "profile_public.html",
            user_id=str(user_id),
        )


    @app.get("/servers/<int:guild_id>")
    @require_web_access("web:view_dashboard")
    def server_page(guild_id):


        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "server.html",
            guild_id=guild_id
        )
        
    
    # ========================================================
    # SERVER MEMBERS PAGE
    # ========================================================

    @app.get("/servers/<int:guild_id>/members")
    @require_web_access("web:view_members")
    def server_members_page(guild_id):


        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "server_members.html",
            guild_id=guild_id
        ) 
    
    
# ========================================================
# SERVER CHANNELS PAGE
# ========================================================

    @app.get(
        "/servers/<int:guild_id>/channels"
    )
    @require_web_access("web:view_channels")
    def server_channels_page(
        guild_id
    ):


        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(
            "channels.html",
            guild_id=guild_id
        )
        
    
    
# ========================================================
# LIVE VOICE VIEWER PAGE
# ========================================================

    @app.get(
        "/servers/<int:guild_id>/voice"
    )
    @require_web_access("web:view_voice")
    def server_voice_page(
        guild_id
    ):


        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(
            "voice.html",
            guild_id=guild_id
        )



# ========================================================
# CHANNEL DETAILS PAGE
# ========================================================

    @app.get(
        "/servers/<int:guild_id>/channels/<int:channel_id>"
    )
    @require_web_access("web:view_channels")
    def channel_details_page(
        guild_id,
        channel_id
    ):


        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(
            "channel_details.html",
            guild_id=guild_id,
            channel_id=channel_id
        )
      
    @app.route("/logger")
    def logger():

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        return redirect(
            url_for("servers")
        )


    @app.get(
        "/servers/<int:guild_id>/logger"
    )
    @require_web_access("web:view_logger")
    def server_logger_page(
        guild_id
    ):



        session[
            "selected_guild_id"
        ] = str(
            guild_id
        )


        return render_template(
            "logger/dashboard.html",
            guild_id=guild_id
        )
        
    @app.get("/servers/<int:guild_id>/logging")
    @require_web_access_any("web:manage_permissions", "web:manage_logs")
    def server_logging_page(guild_id):

        # Logger settings merged into the combined Settings page
        # (2026-11-15); the old URL redirects to its Logger tab so
        # bookmarks keep working.
        session["selected_guild_id"] = str(guild_id)
        return redirect(url_for("permissions.page", gid=guild_id, tab="logger"))

    @app.route(
    "/servers/<int:guild_id>/activity"
    )
    @require_web_access("web:view_activity")
    def server_activity_page(guild_id):


        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "server_activity.html",
            guild_id=guild_id
        )
            
            
            
# ========================================================
# FAVICON
# ========================================================

    @app.get("/favicon.ico")
    def favicon():

        # Bridge split: the bot avatar comes from the bridge status
        # endpoint. When the bot is down, fall back to the static
        # favicon (the fallback already existed).
        try:
            from web.services import bridge

            user = (bridge.status().get("user") or {})
            avatar_url = user.get("avatar_url")
            if avatar_url:
                return redirect(avatar_url)
        except Exception as exc:

            print(
                f"[Favicon] Failed to load bot avatar: {exc}"
            )

        return redirect(
            url_for(
                "static",
                filename="favicon.svg"
            )
        )
        
        
        
        
# ========================================================
# SERVER ROLES PAGE
# ========================================================

    @app.get(
        "/servers/<int:guild_id>/roles"
    )
    @require_web_access("web:view_roles")
    def server_roles_page(
        guild_id
    ):



        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(

            "roles.html",

            guild_id=guild_id

        )
        
        
        


    # ========================================================
    # LEADERBOARD PAGE
    # ========================================================

    @app.get(
        "/servers/<int:guild_id>/leaderboard"
    )
    @require_web_access("web:view_leaderboard")
    def leaderboard_page(
        guild_id
    ):


        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(
            "leaderboard.html",
            guild_id=guild_id
        )

# ========================================================
# EVENT DETAILS PAGE (moved from pages.py)
# ========================================================

    @app.get("/servers/<int:guild_id>/events/<int:event_id>")
    @require_web_access("web:view_activity")
    def event_details_page(guild_id, event_id):


        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "event_details.html",
            guild_id=guild_id,
            event_id=event_id
        )


    # Connect this process to the shared Postgres pool. Every direct
    # DB read (leaderboard, directory, friends, profiles, feed, ...)
    # runs on the website's local loop and fails with
    # "DatabaseBackend is not running" until this connects -- the bot
    # connects once in its on_ready, but this process never did.
    # Idempotent; a DB outage only logs a warning and the site still
    # starts (DB-backed pages degrade to 503 as before).
    try:
        from web.services.web_db import ensure_connected

        ensure_connected()
    except Exception as exc:  # noqa: BLE001 - startup must not fail
        print("[Web] WARNING: database connect at startup failed: %s" % exc)

    return app


# ============================================================
# STANDALONE TEST
# ============================================================

if __name__ == "__main__":

    from web.serve import run_server, get_host_port

    app = create_app(bot=None)

    host, port = get_host_port()
    # Standalone test defaults to localhost only
    if os.environ.get("WEB_HOST") is None:
        host = "127.0.0.1"
    run_server(app, host=host, port=port)
