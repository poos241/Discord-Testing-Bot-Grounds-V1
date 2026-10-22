# ============================================================
# Debug blueprint — toggle API + request logging + debug panel data
# ============================================================

import time
from collections import deque
from flask import Blueprint, jsonify, request, session

from web import debug as dbg
from web.security.decorators import require_guild_access
from web.blueprints.auth import get_csrf_token
import secrets

debug_api = Blueprint("debug_api", __name__)

# Ring buffer of recent requests (in-memory, last 100)
_recent_requests = deque(maxlen=100)


def init_request_logging(app):
    """Attach before/after request hooks for debug logging."""

    @app.before_request
    def _dbg_before():
        request._dbg_start = time.time()

    @app.after_request
    def _dbg_after(response):
        if dbg.is_enabled():
            elapsed = (time.time() - getattr(request, "_dbg_start", time.time())) * 1000
            entry = {
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "ms": round(elapsed, 1),
                "time": time.strftime("%H:%M:%S"),
            }
            _recent_requests.append(entry)
            # Only log API calls and errors to console (not every static file)
            if request.path.startswith("/api/") or response.status_code >= 400:
                dbg.log("web", f"{request.method} {request.path} -> "
                               f"{response.status_code} ({elapsed:.1f}ms)")
        return response


def _check_csrf():
    token = request.headers.get("X-CSRF-Token", "")
    expected = get_csrf_token()
    if not expected or not secrets.compare_digest(str(token), str(expected)):
        return jsonify({"success": False, "error": "CSRF check failed."}), 403
    return None


@debug_api.get("/api/debug/status")
def debug_status():
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    return jsonify({
        "success": True,
        "enabled": dbg.is_enabled(),
    })


@debug_api.post("/api/debug/toggle")
def debug_toggle():
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    denied = _check_csrf()
    if denied:
        return denied
    data = request.get_json(silent=True) or {}
    if "enabled" in data:
        on = bool(data["enabled"])
    else:
        on = not dbg.is_enabled()
    dbg.set_enabled(on)
    dbg.log("web", f"Debug {'ENABLED' if on else 'DISABLED'} via web UI")
    return jsonify({"success": True, "enabled": on})


@debug_api.get("/api/debug/requests")
def debug_requests():
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    return jsonify({
        "success": True,
        "enabled": dbg.is_enabled(),
        "requests": list(_recent_requests)[::-1],  # newest first
    })
