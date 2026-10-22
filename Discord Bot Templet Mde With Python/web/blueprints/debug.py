# ============================================================
# Debug blueprint — toggle API + request logging + debug panel data
#
# When debug is on, EVERY request is logged in Flask dev-server style:
#   192.168.1.129 - - [21/Oct/2026 16:29:46] "GET /servers HTTP/1.1" 200 -
# to both the console and data/web_debug.log
# ============================================================

import time
from collections import deque
from pathlib import Path
from flask import Blueprint, jsonify, request, session, render_template

from web import debug as dbg
from web.blueprints.auth import get_csrf_token
import secrets

debug_api = Blueprint("debug_api", __name__)

# Ring buffer of recent requests (in-memory, last 100)
_recent_requests = deque(maxlen=100)

# Web debug log file (next to the bot's data/debug.log)
_LOG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "web_debug.log"
_BOT_LOG_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "debug.log"


def _write_web_log(line: str):
    """Append a line to data/web_debug.log."""
    try:
        _LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def init_request_logging(app):
    """Attach before/after request hooks for debug logging."""

    @app.before_request
    def _dbg_before():
        request._dbg_start = time.time()

    @app.after_request
    def _dbg_after(response):
        if dbg.is_enabled():
            elapsed = (time.time() - getattr(request, "_dbg_start", time.time())) * 1000

            # Flask dev-server style log line
            remote = request.remote_addr or "-"
            ts = time.strftime("%d/%b/%Y %H:%M:%S")
            proto = request.environ.get("SERVER_PROTOCOL", "HTTP/1.1")
            # Strip query string for cleaner logs, but note if present
            path = request.path
            if request.query_string:
                path = f"{path}?{request.query_string.decode('utf-8', 'replace')}"
            size = response.content_length
            size_str = str(size) if size is not None else "-"
            log_line = (
                f'{remote} - - [{ts}] "{request.method} {path} {proto}" '
                f"{response.status_code} {size_str} ({elapsed:.1f}ms)"
            )
            print(log_line, flush=True)
            _write_web_log(log_line)

            # Capture a snippet of the response body for the inspector
            # (only for text/JSON, truncated to 2KB)
            body_snippet = ""
            try:
                ctype = response.content_type or ""
                if any(t in ctype for t in ("json", "text", "html")):
                    raw_body = response.get_data(as_text=True)
                    if raw_body:
                        body_snippet = raw_body[:2048]
                        if len(raw_body) > 2048:
                            body_snippet += f"\n... [truncated, {len(raw_body)} chars total]"
            except Exception:
                pass

            entry = {
                "method": request.method,
                "path": request.path,
                "status": response.status_code,
                "ms": round(elapsed, 1),
                "time": time.strftime("%H:%M:%S"),
                "body": body_snippet,
            }
            _recent_requests.append(entry)
        return response


# Cache the panel HTML at startup (read once, no Jinja needed)
_PANEL_HTML = None

def _get_panel_html():
    global _PANEL_HTML
    if _PANEL_HTML is None:
        try:
            panel_path = Path(__file__).resolve().parent.parent / "templates" / "debug_panel.html"
            _PANEL_HTML = panel_path.read_text(encoding="utf-8")
        except Exception as e:
            _PANEL_HTML = ""
            print(f"[DEBUG][web] Failed to load debug panel: {e}", flush=True)
    return _PANEL_HTML


def init_panel_injection(app):
    """Inject the debug panel into every HTML page (logged-in users only).

    This runs after the response is built. If the page is HTML and doesn't
    already have the panel, it's inserted before </body>. This covers
    standalone pages that don't extend base.html.
    """

    @app.after_request
    def _inject_dbg_panel(response):
        try:
            if not session.get("user"):
                return response
            ctype = response.content_type or ""
            if "text/html" not in ctype:
                return response
            html = response.get_data(as_text=True)
            if "</body>" not in html or 'id="dbg-fab"' in html:
                return response
            panel_html = _get_panel_html()
            if not panel_html:
                _write_web_log("[DEBUG][web] Panel injection skipped: no panel HTML")
                return response
            html = html.replace("</body>", panel_html + "\n</body>", 1)
            response.set_data(html)
            # Update content length since we modified the body
            response.content_length = len(html.encode("utf-8"))
        except Exception as e:
            # Log instead of silently swallowing
            try:
                _write_web_log(f"[DEBUG][web] Panel injection error: {e}")
            except Exception:
                pass
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
    msg = f"Debug {'ENABLED' if on else 'DISABLED'} via web UI"
    print(f"[DEBUG][web] {msg}", flush=True)
    _write_web_log(f"[DEBUG][web] {msg}")
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


@debug_api.post("/api/debug/clear-logs")
def debug_clear_logs():
    """Truncate both debug log files."""
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    denied = _check_csrf()
    if denied:
        return denied
    cleared = []
    for lf in (_LOG_FILE, _BOT_LOG_FILE):
        try:
            lf.parent.mkdir(parents=True, exist_ok=True)
            lf.write_text("", encoding="utf-8")
            cleared.append(lf.name)
        except Exception:
            pass
    msg = f"Cleared logs: {', '.join(cleared) if cleared else 'none'}"
    print(f"[DEBUG][web] {msg}", flush=True)
    return jsonify({"success": True, "cleared": cleared})


@debug_api.get("/api/debug/bot-status")
def debug_bot_status():
    """Check if the Discord bot is alive and responsive."""
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    status = {
        "connected": False,
        "latency_ms": None,
        "guild_count": 0,
        "guilds": [],
        "user": None,
    }
    try:
        from web.services.discord_state import discord_state
        bot = discord_state.get_bot()
        if bot is not None:
            try:
                status["connected"] = bool(bot.is_ready())
            except Exception:
                pass
            try:
                latency = getattr(bot, "latency", None)
                if latency is not None:
                    status["latency_ms"] = round(latency * 1000, 1)
            except Exception:
                pass
            try:
                guilds = list(getattr(bot, "guilds", []) or [])
                status["guild_count"] = len(guilds)
                status["guilds"] = [
                    {"id": str(g.id), "name": g.name} for g in guilds[:20]
                ]
            except Exception:
                pass
            try:
                u = getattr(bot, "user", None)
                if u:
                    status["user"] = str(u)
            except Exception:
                pass
    except Exception as e:
        status["error"] = str(e)
    return jsonify({"success": True, **status})


@debug_api.get("/api/debug/bundle")
def debug_bundle():
    """Build a copy-paste debug bundle: requests, errors, bot status, config."""
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    import os
    lines = []
    lines.append("=== DEBUG BUNDLE ===")
    lines.append(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    # Bot status (reuse the logic)
    try:
        from web.services.discord_state import discord_state
        bot = discord_state.get_bot()
        if bot is not None and bot.is_ready():
            lines.append(f"Bot: CONNECTED as {bot.user} (latency {round(bot.latency*1000,1)}ms)")
            lines.append(f"Guilds: {len(list(bot.guilds or []))}")
        else:
            lines.append("Bot: NOT CONNECTED / NOT READY")
    except Exception as e:
        lines.append(f"Bot: check failed ({e})")
    lines.append("")

    # Config (non-secret)
    lines.append("Config:")
    for key in ("WEB_HOST", "WEB_PORT", "WEB_ENABLED", "DEBUG"):
        lines.append(f"  {key}={os.environ.get(key, '(not set)')}")
    lines.append("")

    # Recent requests (errors first)
    reqs = list(_recent_requests)[::-1]
    errors = [r for r in reqs if r["status"] >= 400]
    lines.append(f"Recent requests ({len(reqs)} total, {len(errors)} errors):")
    for r in reqs[:30]:
        flag = " SLOW" if r["ms"] > 1000 else ""
        lines.append(f"  {r['method']} {r['path']} -> {r['status']} ({r['ms']}ms){flag}")
        if r["status"] >= 400 and r.get("body"):
            # Include first 500 chars of error body
            body = r["body"][:500].replace("\n", " ")
            lines.append(f"    Response: {body}")
    lines.append("")

    # Tail of web log
    try:
        log_lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
        lines.append(f"Server log (last 20 of {len(log_lines)} lines):")
        for ll in log_lines[-20:]:
            lines.append(f"  {ll}")
    except Exception:
        lines.append("Server log: unavailable")

    return jsonify({"success": True, "bundle": "\n".join(lines)})


@debug_api.get("/api/debug/weblog")
def debug_weblog():
    """Return the tail of data/web_debug.log for viewing in the panel."""
    if not session.get("user"):
        return jsonify({"success": False, "error": "Not logged in."}), 401
    try:
        lines = _LOG_FILE.read_text(encoding="utf-8").splitlines()
        tail = lines[-100:]  # last 100 lines
    except Exception:
        tail = []
    return jsonify({
        "success": True,
        "enabled": dbg.is_enabled(),
        "lines": tail,
    })
