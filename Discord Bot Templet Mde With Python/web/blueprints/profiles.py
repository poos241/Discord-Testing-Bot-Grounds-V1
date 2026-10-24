"""End-user profile customization API.

Stores per-user profile settings (bio + accent color) in
``data/profiles.json`` (created at runtime, never committed),
keyed by Discord user ID.
"""

import json
import os
import re
import secrets

from flask import (
    Blueprint,
    jsonify,
    request,
    session,
)

from web.blueprints.auth import get_csrf_token
from web.security.decorators import require_login


profiles_api = Blueprint(
    "profiles",
    __name__,
    url_prefix="/api",
)


# data/profiles.json lives next to the bot's other data files:
# <bot root>/data/profiles.json
DATA_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(__file__),
        "..",
        "..",
        "data",
    )
)
PROFILES_PATH = os.path.join(
    DATA_DIR,
    "profiles.json",
)

MAX_BIO_LEN = 500
ACCENT_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
DEFAULT_PROFILE = {
    "bio": "",
    "accent": "#5865F2",
}


def _load_profiles():

    try:

        with open(
            PROFILES_PATH,
            encoding="utf-8",
        ) as f:

            data = json.load(f)

        if isinstance(data, dict):

            return data

    except (OSError, ValueError):

        pass

    return {}


def _save_profiles(data):

    os.makedirs(
        DATA_DIR,
        exist_ok=True,
    )

    tmp_path = PROFILES_PATH + ".tmp"

    with open(
        tmp_path,
        "w",
        encoding="utf-8",
    ) as f:

        json.dump(
            data,
            f,
            indent=2,
        )

    os.replace(
        tmp_path,
        PROFILES_PATH,
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


@profiles_api.get(
    "/profile"
)
@require_login
def get_profile():

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    saved = _load_profiles().get(user_id, {})

    profile = {
        "bio": saved.get("bio", DEFAULT_PROFILE["bio"]),
        "accent": saved.get("accent", DEFAULT_PROFILE["accent"]),
    }

    return jsonify({

        "success": True,

        "user": {
            "id": user.get("id"),
            "username": user.get("username"),
            "global_name": user.get("global_name"),
            "avatar": user.get("avatar"),
        },

        "profile": profile,

    })


@profiles_api.post(
    "/profile"
)
@require_login
def save_profile():

    denied = _check_csrf()

    if denied is not None:

        return denied

    user = session.get("user") or {}
    user_id = str(user.get("id", ""))

    if not user_id:

        return jsonify({
            "success": False,
            "error": "Not logged in.",
        }), 401

    body = request.get_json(silent=True) or {}

    bio = str(body.get("bio", "")).strip()[:MAX_BIO_LEN]
    accent = str(body.get("accent", "")).strip()

    if not ACCENT_RE.match(accent):

        accent = DEFAULT_PROFILE["accent"]

    data = _load_profiles()

    data[user_id] = {
        "bio": bio,
        "accent": accent,
    }

    try:

        _save_profiles(data)

    except OSError as exc:

        print(
            "[Profiles API] Failed to save "
            f"profiles.json: {exc}"
        )

        return jsonify({
            "success": False,
            "error": "Could not save profile.",
        }), 500

    return jsonify({

        "success": True,

        "profile": data[user_id],

    })
