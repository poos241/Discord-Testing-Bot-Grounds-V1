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

from web.blueprints.roles import roles_api

from web.blueprints.logger import logger_api
from web.blueprints.dashboard import dashboard_api

from web.services.discord_state import discord_state

# from web.blueprints.channels import channels_api
# from web.blueprints.roles import roles_api


# ============================================================
# CREATE APP
# ============================================================

def create_app(bot):

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

    # Store Discord bot inside Flask config.
    app.config["BOT"] = bot
    app.config["DISCORD_BOT"] = bot

    # Hand the live bot to the discord_state shim used by blueprints/services.
    discord_state.set_bot(bot)

    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024

    @app.context_processor
    def inject_security_helpers():
        from web.blueprints.auth import get_csrf_token
        from web.services.permissions import (
            get_access_level,
            has_access,
        )

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

        return {
            "csrf_token": get_csrf_token,
            "can": can,
            "can_any": can_any,
            "selected_guild_level": selected_guild_level,
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
    
    app.register_blueprint(servers_api)
    
    app.register_blueprint(health_api)
    
    app.register_blueprint(channels_api)
    
    app.register_blueprint(member_stats_api)
    
    app.register_blueprint(explorer_api)
    
    app.register_blueprint(channel_details_api)
    
    app.register_blueprint(server_overview_api)
    
    app.register_blueprint(event_stats_api)
    
    app.register_blueprint(search_api)
    
    app.register_blueprint(member_details_api)
    
    app.register_blueprint(role_details_api)
    
    app.register_blueprint(roles_api)
    
    app.register_blueprint(auth_api)
    
    

# ========================================================
# HOME
# ========================================================

    @app.route("/")
    def home():

        if not session.get("user"):

            return render_template(
                "auth/login.html"
            )

        
        return redirect(
            url_for("servers")
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
    def server_dashboard(guild_id):

        from web.services.permissions import (
            is_guild_member
        )

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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


    @app.get("/servers/<int:guild_id>")
    def server_page(guild_id):

        from web.services.permissions import (
            is_guild_member
        )

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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
    def server_members_page(guild_id):

        from web.services.permissions import (
            is_guild_member
        )

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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
    def server_channels_page(
        guild_id
    ):

        from web.services.permissions import (
            is_guild_member
        )


        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )


        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

        session["selected_guild_id"] = str(
            guild_id
        )


        return render_template(
            "channels.html",
            guild_id=guild_id
        )
        
    
    
# ========================================================
# CHANNEL DETAILS PAGE
# ========================================================

    @app.get(
        "/servers/<int:guild_id>/channels/<int:channel_id>"
    )
    def channel_details_page(
        guild_id,
        channel_id
    ):

        from web.services.permissions import (
            is_guild_member
        )


        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )


        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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
    def server_logger_page(
        guild_id
    ):

        from web.blueprints.auth import (
            user_can_manage_guild
        )


        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )


        if not user_can_manage_guild(
            guild_id
        ):

            return render_template(
                "auth/login.html",
                error=(
                    "You do not have permission "
                    "to view this server's logger."
                )
            ), 403


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
    def server_logging_page(guild_id):

        from web.blueprints.auth import user_can_manage_guild

        if not session.get("user"):
            return redirect(url_for("auth.login"))

        if not user_can_manage_guild(guild_id):
            return render_template(
                "auth/login.html",
                error="You do not have permission to manage logger settings for this server."
            ), 403

        session["selected_guild_id"] = str(guild_id)
        return render_template("logger/logging.html", guild_id=guild_id)

    @app.route(
    "/servers/<int:guild_id>/activity"
    )
    def server_activity_page(guild_id):

        from web.services.permissions import (
            is_guild_member
        )

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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

        bot = app.config.get(
            "BOT"
        )


        if (
            bot is not None
            and getattr(
                bot,
                "user",
                None
            ) is not None
        ):

            try:

                avatar_url = str(
                    bot.user.display_avatar.url
                )

                return redirect(
                    avatar_url
                )

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
    def server_roles_page(
        guild_id
    ):

        from web.services.permissions import (
            is_guild_member
        )


        if not session.get("user"):

            return redirect(
                url_for(
                    "auth.login"
                )
            )


        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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
    def leaderboard_page(
        guild_id
    ):

        from web.services.permissions import (
            is_guild_member
        )


        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )


        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

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
    def event_details_page(guild_id, event_id):

        from web.services.permissions import (
            is_guild_member
        )

        if not session.get("user"):

            return redirect(
                url_for("auth.login")
            )

        if not is_guild_member(
            guild_id
        ):

            return render_template(
                "403.html",
                guild_id=guild_id,
            ), 403

        session["selected_guild_id"] = str(
            guild_id
        )

        return render_template(
            "event_details.html",
            guild_id=guild_id,
            event_id=event_id
        )


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