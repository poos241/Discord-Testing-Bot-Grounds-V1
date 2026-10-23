import json
import secrets
import urllib.parse
import urllib.request
import urllib.error
import threading
import time

from flask import (
    Blueprint,
    redirect,
    request,
    session,
    jsonify,
    render_template,
    url_for,
)

from web.config import (
    DISCORD_CLIENT_ID,
    DISCORD_CLIENT_SECRET,
    DISCORD_REDIRECT_URI,
    PUBLIC_BASE_URL,
)
from web.security.decorators import require_login


auth_api = Blueprint(
    "auth",
    __name__,
)


DISCORD_AUTHORIZE_URL = (
    "https://discord.com/oauth2/authorize"
)

DISCORD_TOKEN_URL = (
    "https://discord.com/api/oauth2/token"
)

DISCORD_API_URL = (
    "https://discord.com/api"
)


# =========================================================
# SERVER-SIDE AUTH STORAGE
# =========================================================
#
# IMPORTANT:
#
# Do NOT store Discord access tokens or OAuth state inside
# Flask's browser cookie session.
#
# Flask's default session is cookie-based.
#
# That caused:
#
#   - oversized session cookies
#   - OAuth state failures
#   - problems when accessing the dashboard over LAN
#
# Instead we keep the sensitive OAuth information here.
#
# Later, this can easily be moved to Redis/database storage.
# =========================================================

_AUTH_LOCK = threading.RLock()

_AUTH_SESSIONS = {}

_PENDING_OAUTH = {}

# Cached Discord guild list per authenticated web session.
# This prevents every page/API request from hitting Discord /users/@me/guilds.
_GUILD_CACHE = {}
GUILD_CACHE_TTL = 60
GUILD_CACHE_STALE_TTL = 300
# Session IDs with a Discord guild fetch currently in flight.
# Prevents concurrent page/API requests from bursting Discord with
# duplicate calls (which is what triggers the 429s).
_GUILD_FETCH_INFLIGHT = set()


AUTH_SESSION_MAX_AGE = 60 * 60 * 24 * 7

OAUTH_STATE_MAX_AGE = 60 * 10


# =========================================================
# REDIRECT URI
# =========================================================

def get_redirect_uri():

    if PUBLIC_BASE_URL:

        return (
            PUBLIC_BASE_URL
            + "/callback"
        )

    return DISCORD_REDIRECT_URI


# =========================================================
# DISCORD API REQUEST
# =========================================================

def discord_request(
    url,
    method="GET",
    data=None,
    access_token=None,
):

    headers = {
        "User-Agent":
            "Kush Bush Dashboard/1.0"
    }

    if access_token:

        headers[
            "Authorization"
        ] = f"Bearer {access_token}"

    encoded_data = None

    if data is not None:

        encoded_data = urllib.parse.urlencode(
            data
        ).encode("utf-8")

        headers[
            "Content-Type"
        ] = "application/x-www-form-urlencoded"

    req = urllib.request.Request(
        url,
        data=encoded_data,
        headers=headers,
        method=method,
    )

    with urllib.request.urlopen(
        req,
        timeout=15,
    ) as response:

        body = response.read().decode(
            "utf-8"
        )

        if not body:

            return {}

        return json.loads(body)


# =========================================================
# CLEAN OLD AUTH DATA
# =========================================================

def cleanup_auth_storage():

    now = time.time()

    with _AUTH_LOCK:

        expired_sessions = [

            session_id

            for session_id, auth_data
            in _AUTH_SESSIONS.items()

            if now - auth_data.get(
                "created_at",
                now
            ) > AUTH_SESSION_MAX_AGE

        ]

        for session_id in expired_sessions:

            _AUTH_SESSIONS.pop(
                session_id,
                None
            )


        expired_states = [

            state

            for state, oauth_data
            in _PENDING_OAUTH.items()

            if now - oauth_data.get(
                "created_at",
                now
            ) > OAUTH_STATE_MAX_AGE

        ]

        for state in expired_states:

            _PENDING_OAUTH.pop(
                state,
                None
            )

        expired_guild_cache = [
            sid
            for sid, cached in _GUILD_CACHE.items()
            if now - cached.get("fetched_at", now) > GUILD_CACHE_STALE_TTL
        ]

        for sid in expired_guild_cache:
            _GUILD_CACHE.pop(sid, None)


# =========================================================
# GET SERVER-SIDE AUTH SESSION
# =========================================================

def get_auth_session():

    session_id = session.get(
        "auth_sid"
    )

    if not session_id:

        return None

    cleanup_auth_storage()

    with _AUTH_LOCK:

        auth_data = _AUTH_SESSIONS.get(
            session_id
        )

        if not auth_data:

            return None

        auth_data["last_seen"] = time.time()

        return auth_data


def get_csrf_token():
    """Return the CSRF token stored in the server-side auth session.

    Keeping this token beside the OAuth session avoids race conditions caused
    by mutating Flask's signed browser cookie from concurrent AJAX requests.
    """
    auth_data = get_auth_session()
    if not auth_data:
        return ""

    with _AUTH_LOCK:
        token = auth_data.get("csrf_token")
        if not token:
            token = secrets.token_urlsafe(32)
            auth_data["csrf_token"] = token
        return token


# =========================================================
# LOGIN
# =========================================================

@auth_api.get("/login")
def login():

    if session.get("auth_sid"):

        if get_auth_session():

            return redirect(
                url_for("servers")
            )

        session.pop(
            "auth_sid",
            None
        )

        session.pop(
            "user",
            None
        )


    # -----------------------------------------------------
    # Create OAuth state
    # -----------------------------------------------------

    state = secrets.token_urlsafe(
        32
    )


    with _AUTH_LOCK:

        _PENDING_OAUTH[state] = {

            "created_at":
                time.time(),

            "redirect_uri":
                get_redirect_uri(),

        }


    # -----------------------------------------------------
    # Discord OAuth request
    # -----------------------------------------------------

    params = {

        "client_id":
            DISCORD_CLIENT_ID,

        "redirect_uri":
            get_redirect_uri(),

        "response_type":
            "code",

        "scope":
            "identify guilds",

        "state":
            state,

    }


    authorize_url = (

        DISCORD_AUTHORIZE_URL

        + "?"

        + urllib.parse.urlencode(
            params
        )

    )


    return redirect(
        authorize_url
    )


# =========================================================
# CALLBACK
# =========================================================

@auth_api.get("/callback")
def callback():

    error = request.args.get(
        "error"
    )


    if error:

        return render_template(

            "auth/login.html",

            error=(
                "Discord authorization was cancelled."
            )

        ), 400


    returned_state = request.args.get(
        "state"
    )


    code = request.args.get(
        "code"
    )


    # -----------------------------------------------------
    # Validate state SERVER-SIDE
    # -----------------------------------------------------

    if not returned_state:

        print(
            "[Web Auth] OAuth callback missing state."
        )

        return render_template(

            "auth/login.html",

            error=(
                "Discord did not return an OAuth state."
            )

        ), 400


    with _AUTH_LOCK:

        oauth_data = _PENDING_OAUTH.pop(
            returned_state,
            None
        )


    if not oauth_data:

        print(
            "[Web Auth] OAuth state was not found "
            "or has expired."
        )

        return render_template(

            "auth/login.html",

            error=(
                "Your Discord login session expired "
                "or the OAuth request was invalid. "
                "Please try logging in again."
            )

        ), 400


    # -----------------------------------------------------
    # Validate code
    # -----------------------------------------------------

    if not code:

        return render_template(

            "auth/login.html",

            error=(
                "Discord did not return "
                "an authorization code."
            )

        ), 400


    try:

        redirect_uri = oauth_data.get(
            "redirect_uri"
        ) or get_redirect_uri()


        print(
            "[Web Auth] OAuth callback accepted."
        )

        print(
            f"[Web Auth] Redirect URI: {redirect_uri}"
        )


        # -------------------------------------------------
        # Exchange OAuth code for token
        # -------------------------------------------------

        token = discord_request(

            DISCORD_TOKEN_URL,

            method="POST",

            data={

                "client_id":
                    DISCORD_CLIENT_ID,

                "client_secret":
                    DISCORD_CLIENT_SECRET,

                "grant_type":
                    "authorization_code",

                "code":
                    code,

                "redirect_uri":
                    redirect_uri,

            },

        )


        access_token = token.get(
            "access_token"
        )


        if not access_token:

            raise RuntimeError(

                "Discord did not return "
                "an access token."

            )


        # -------------------------------------------------
        # Get Discord user
        # -------------------------------------------------

        user = discord_request(

            f"{DISCORD_API_URL}/users/@me",

            access_token=access_token,

        )


        if not user.get("id"):

            raise RuntimeError(

                "Discord did not return "
                "a valid user."

            )


        user_data = {

            "id":
                str(
                    user.get("id")
                ),

            "username":
                user.get("username"),

            "global_name":
                user.get("global_name"),

            "avatar":
                user.get("avatar"),

            "discriminator":
                user.get("discriminator"),

        }


        # -------------------------------------------------
        # Create server-side authentication session
        # -------------------------------------------------

        auth_session_id = secrets.token_urlsafe(
            32
        )


        with _AUTH_LOCK:

            _AUTH_SESSIONS[
                auth_session_id
            ] = {

                "created_at":
                    time.time(),

                "last_seen":
                    time.time(),

                "user":
                    user_data,

                "access_token":
                    access_token,

                # CSRF token stays server-side with the authenticated
                # session instead of being written into the browser cookie.
                "csrf_token":
                    secrets.token_urlsafe(32),

            }


        # -------------------------------------------------
        # Flask browser session contains ONLY small data
        # -------------------------------------------------

        session.clear()


        session[
            "auth_sid"
        ] = auth_session_id


        session[
            "user"
        ] = user_data


        session.permanent = True


        print(
            "[Web Auth] Discord login successful."
        )

        print(
            f"[Web Auth] User: "
            f"{user_data.get('username')} "
            f"({user_data.get('id')})"
        )


        return redirect(
            url_for("dashboard")
        )


    except Exception as exc:

        print(
            f"[Web Auth] Discord OAuth failed: {exc}"
        )


        return render_template(

            "auth/login.html",

            error=(

                "Discord login failed. "
                "Check the terminal for details."

            )

        ), 500


# =========================================================
# LOGOUT
# =========================================================

@auth_api.get("/logout")
def logout():

    auth_sid = session.get(
        "auth_sid"
    )


    if auth_sid:

        with _AUTH_LOCK:

            _AUTH_SESSIONS.pop(
                auth_sid,
                None
            )

            _GUILD_CACHE.pop(
                auth_sid,
                None
            )


    session.clear()


    return redirect(
        url_for("home")
    )


# =========================================================
# CURRENT USER
# =========================================================

@auth_api.get("/api/auth/me")
def current_user():

    auth_data = get_auth_session()


    if not auth_data:

        session.pop(
            "auth_sid",
            None
        )

        session.pop(
            "user",
            None
        )


        return jsonify({

            "authenticated":
                False,

            "user":
                None,

        })


    user = auth_data.get(
        "user"
    )


    return jsonify({

        "authenticated":
            True,

        "user":
            user,

    })


# =========================================================
# GET CURRENT USER'S DISCORD GUILDS
# =========================================================

def _guild_cache_backoff_seconds():
    """Fallback wait before retrying guild fetches after a 429."""
    return 5


def get_user_guilds(force_refresh=False):

    auth_data = get_auth_session()
    if not auth_data:
        return []

    session_id = session.get("auth_sid")
    access_token = auth_data.get("access_token")
    if not session_id or not access_token:
        return []

    now = time.time()

    with _AUTH_LOCK:
        cached = _GUILD_CACHE.get(session_id)
        if cached:
            # If Discord rate-limited us, respect its retry_after and serve
            # the last known list instead of hammering the endpoint again.
            if now < cached.get("retry_after", 0):
                return list(cached.get("guilds", []))
            if not force_refresh:
                age = now - cached.get("fetched_at", 0)
                if age <= GUILD_CACHE_TTL:
                    return list(cached.get("guilds", []))
        # If another thread is already refreshing, wait for it instead of
        # firing a duplicate request (bursts are what trigger the 429s).
        if session_id in _GUILD_FETCH_INFLIGHT:
            wait_for_other = True
        else:
            _GUILD_FETCH_INFLIGHT.add(session_id)
            wait_for_other = False

    if wait_for_other:
        for _ in range(30):  # up to ~3s
            time.sleep(0.1)
            with _AUTH_LOCK:
                cached = _GUILD_CACHE.get(session_id)
                if cached:
                    age = time.time() - cached.get("fetched_at", 0)
                    if age <= GUILD_CACHE_TTL:
                        return list(cached.get("guilds", []))
        # The other fetch didn't finish in time; try ourselves.
        with _AUTH_LOCK:
            _GUILD_FETCH_INFLIGHT.discard(session_id)
            _GUILD_FETCH_INFLIGHT.add(session_id)

    try:
        guilds = discord_request(
            f"{DISCORD_API_URL}/users/@me/guilds",
            access_token=access_token,
        )

        if not isinstance(guilds, list):
            guilds = []

        with _AUTH_LOCK:
            _GUILD_CACHE[session_id] = {
                "guilds": guilds,
                "fetched_at": time.time(),
                "retry_after": 0,
            }

        return list(guilds)

    except urllib.error.HTTPError as exc:
        # Discord is rate limiting us: honor its retry_after so we stop
        # immediately instead of retrying into the limit on every request.
        retry_after = _guild_cache_backoff_seconds()
        if exc.code == 429:
            try:
                body = exc.read().decode("utf-8")
                data = json.loads(body)
                retry_after = float(data.get("retry_after", retry_after))
            except Exception:
                pass
            retry_after = min(max(retry_after, 1), 300)
            print(
                "[Web Auth] Discord rate limited (429); "
                f"backing off guild fetches for {retry_after:.1f}s"
            )
        else:
            print(f"[Web Auth] Failed to retrieve Discord guilds: {exc}")

        with _AUTH_LOCK:
            _GUILD_FETCH_INFLIGHT.discard(session_id)
            cached = _GUILD_CACHE.get(session_id) or {}
            if exc.code == 429:
                cached["retry_after"] = time.time() + retry_after + 1
            if "fetched_at" not in cached:
                cached["fetched_at"] = 0
            if "guilds" not in cached:
                cached["guilds"] = []
            _GUILD_CACHE[session_id] = cached
            now2 = time.time()
            if cached.get("guilds") and now2 - cached.get("fetched_at", 0) <= GUILD_CACHE_STALE_TTL:
                # A temporary 429/network failure must not turn a valid
                # logged-in user into a 403 if we have a recently known
                # permission snapshot.
                return list(cached.get("guilds", []))

        return []

    except Exception as exc:
        print(f"[Web Auth] Failed to retrieve Discord guilds: {exc}")

        with _AUTH_LOCK:
            _GUILD_FETCH_INFLIGHT.discard(session_id)
            # A temporary 429/network failure must not turn a valid logged-in
            # user into a 403 if we have a recently known permission snapshot.
            cached = _GUILD_CACHE.get(session_id)
            if cached and time.time() - cached.get("fetched_at", 0) <= GUILD_CACHE_STALE_TTL:
                return list(cached.get("guilds", []))

        return []


# =========================================================
# CHECK SERVER MANAGEMENT PERMISSION
# =========================================================

def user_can_manage_guild(
    guild_id
):

    if not get_auth_session():

        return False


    guild_id = str(
        guild_id
    )


    guilds = get_user_guilds()


    for guild in guilds:

        if str(
            guild.get("id")
        ) != guild_id:

            continue


        permissions = int(

            guild.get(
                "permissions",
                0
            )

        )


        # Administrator

        if permissions & 0x8:

            return True


        # Manage Server

        if permissions & 0x20:

            return True


        # Server owner

        if guild.get(
            "owner",
            False
        ):

            return True


        return False


    return False


# =========================================================
# GET USER'S MANAGEABLE SERVERS
# =========================================================

def get_manageable_guilds():

    guilds = get_user_guilds()


    manageable = []


    for guild in guilds:

        permissions = int(

            guild.get(
                "permissions",
                0
            )

        )


        is_admin = bool(

            permissions & 0x8

        )


        can_manage = bool(

            permissions & 0x20

        )


        is_owner = bool(

            guild.get(
                "owner",
                False
            )

        )


        if not (
            is_admin
            or can_manage
            or is_owner
        ):

            continue


        manageable.append({

            "id":
                str(
                    guild.get("id")
                ),

            "name":
                guild.get("name"),

            "icon":
                guild.get("icon"),

            "owner":
                is_owner,

            "can_manage":
                True,

            "is_admin":
                is_admin,

        })


    return manageable


# =========================================================
# AUTH DEBUG
# =========================================================

@auth_api.get("/api/auth/debug")
@require_login
def auth_debug():

    auth_data = get_auth_session()


    if not auth_data:

        return jsonify({

            "authenticated":
                False,

            "user":
                None,

            "has_access_token":
                False,

            "guild_count":
                0,

            "manageable_guild_count":
                0,

        })


    user = auth_data.get(
        "user"
    )


    guilds = get_user_guilds()


    manageable = []


    for guild in guilds:

        permissions = int(

            guild.get(
                "permissions",
                0
            )

        )


        is_admin = bool(
            permissions & 0x8
        )


        can_manage = bool(
            permissions & 0x20
        )


        is_owner = bool(
            guild.get(
                "owner",
                False
            )
        )


        if not (
            is_admin
            or can_manage
            or is_owner
        ):

            continue


        manageable.append({

            "id":
                str(
                    guild.get("id")
                ),

            "name":
                guild.get("name"),

            "owner":
                is_owner,

            "is_admin":
                is_admin,

            "can_manage":
                True,

        })


    return jsonify({

        "authenticated":
            True,

        "user":
            user,

        "has_access_token":
            bool(
                auth_data.get(
                    "access_token"
                )
            ),

        "guild_count":
            len(guilds),

        "manageable_guild_count":
            len(manageable),

        "manageable_guilds":
            manageable,

    })
    
    
# =========================================================
# OAUTH DIAGNOSTICS
# =========================================================

@auth_api.get("/api/auth/oauth-status")
@require_login
def oauth_status():

    auth_data = get_auth_session()

    with _AUTH_LOCK:

        pending_states = len(
            _PENDING_OAUTH
        )

        active_sessions = len(
            _AUTH_SESSIONS
        )


    return jsonify({

        "success":
            True,

        "redirect_uri":
            get_redirect_uri(),

        "authenticated":
            bool(auth_data),

        "active_auth_sessions":
            active_sessions,

        "pending_oauth_states":
            pending_states,

        "session_has_auth_sid":
            bool(
                session.get(
                    "auth_sid"
                )
            ),

        "session_has_user":
            bool(
                session.get(
                    "user"
                )
            ),

    })
