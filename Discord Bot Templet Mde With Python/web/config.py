import os

from dotenv import load_dotenv

load_dotenv()


# =========================================================
# DISCORD OAUTH
# =========================================================

DISCORD_CLIENT_ID = os.getenv(
    "DISCORD_CLIENT_ID"
)

DISCORD_CLIENT_SECRET = os.getenv(
    "DISCORD_CLIENT_SECRET"
)


# =========================================================
# OAUTH REDIRECT
# =========================================================
#
# IMPORTANT:
#
# For LAN testing, this needs to be reachable from the
# device being used.
#
# Example:
#
# http://192.168.1.133:5000/callback
#
# This EXACT URL must also exist in the Discord Developer
# Portal OAuth2 Redirects.
# =========================================================

DISCORD_REDIRECT_URI = os.getenv(
    "DISCORD_REDIRECT_URI",
    "http://192.168.1.133:5000/callback"
)


PUBLIC_BASE_URL = os.getenv(
    "PUBLIC_BASE_URL",
    ""
).strip().rstrip("/")


# =========================================================
# FLASK
# =========================================================

SECRET_KEY = os.getenv(
    "WEB_SECRET_KEY"
)


if not SECRET_KEY:

    raise RuntimeError(
        "WEB_SECRET_KEY is not configured."
    )