"""Server Home — one page for every service on the Nitro.

Live status for each service (probed from the server itself, so no
browser CORS / mixed-content problems) plus a link out to that
service's own web UI. Cockpit, Portainer and AdGuard all refuse to be
embedded in another page, and each has its own login, so status +
links is the honest shape. On top of that, this page shows live
numbers that need no extra login: host stats (load, CPU temp, RAM,
disk, bot service uptime), bot stats (guilds, members, latency), and
per-service uptime % + latency averaged from this page's own probes
over the last 24 hours (kept in data/server_home_history.json). Admin-only:
both the page and its status API require the admin tier on a guild the
bot is in (same gate as the restart route), so host/infrastructure
numbers are never visible to a plain logged-in user.

AdGuard + Portainer live numbers need credentials, so they light up
only when the matching .env values exist — otherwise the tile says
how to connect them:
  - AdGuard: ADGUARD_USER + ADGUARD_PASSWORD (the admin login from
    the AdGuard setup wizard) -> /control/stats (queries + blocked).
  - Portainer: PORTAINER_API_KEY (create one in Portainer: your user
    menu -> Access tokens) -> container list (running / total).

Bot controls (restart-only, for now): the restart button asks the
bot to restart itself through the bridge (exit 42, watchdog
relaunches it). The website is a separate process now, so it stays
up while the bot restarts. A hard Stop needs a separate control
service first; that is a later step, not this one.
"""

import base64
import json
import os
import secrets
import shutil
import ssl
import subprocess
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    current_app,
    jsonify,
    render_template,
    request,
    session,
)

from web.blueprints.auth import get_csrf_token, get_user_guilds
from web.security.decorators import require_login
from web.services.permissions import has_access


server_home_api = Blueprint("server_home", __name__)


SERVICES = [
    {
        "key": "bot",
        "name": "Bot Dashboard",
        "desc": "Kush Bush bot + this dashboard. Slash commands, levels, mod panel.",
        "url": "http://127.0.0.1:5000/",
        "port": 5000,
        "scheme": "http",
    },
    {
        "key": "cockpit",
        "name": "Cockpit",
        "desc": "Server health, software updates, terminal in the browser.",
        "url": "https://127.0.0.1:9090/",
        "port": 9090,
        "scheme": "https",
    },
    {
        "key": "portainer",
        "name": "Portainer",
        "desc": "Docker containers, images and volumes.",
        "url": "https://127.0.0.1:9443/",
        "port": 9443,
        "scheme": "https",
    },
    {
        "key": "kuma",
        "name": "Uptime Kuma",
        "desc": "Uptime monitors + alerts for every service on this page.",
        "url": "http://127.0.0.1:3001/",
        "port": 3001,
        "scheme": "http",
    },
    {
        "key": "adguard",
        "name": "AdGuard Home",
        "desc": "Network ad blocking + DNS stats and query log.",
        "url": "http://127.0.0.1/",
        "port": 80,
        "scheme": "http",
    },
]

# Cockpit + Portainer use self-signed certs; accept them for a local probe.
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

_HISTORY_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "server_home_history.json"
_HISTORY_WINDOW_S = 24 * 3600
_HISTORY_LOCK = threading.Lock()


# ============================================================
# PROBES
# ============================================================

def _probe(service):
    """One guarded probe: a dead service must never kill the page."""
    start = time.monotonic()
    try:
        req = urllib.request.Request(service["url"], method="GET")
        with urllib.request.urlopen(req, timeout=3, context=_CTX) as resp:
            resp.read(1)
        return {
            "key": service["key"],
            "status": "up",
            "ms": int((time.monotonic() - start) * 1000),
        }
    except Exception as exc:  # noqa: BLE001 - status page, report it
        return {
            "key": service["key"],
            "status": "down",
            "error": str(exc)[:120],
        }


def _probe_all():
    """Probe every service in parallel so one slow service cannot stall the page."""
    with ThreadPoolExecutor(max_workers=len(SERVICES)) as pool:
        return list(pool.map(_probe, SERVICES))


# ============================================================
# PROBE HISTORY (24h uptime % + average latency, from our own probes)
# ============================================================

def _record_probes(results):
    """Append this round of probes to the history file and summarise.

    Returns {key: {"uptime24h": pct | None, "avg_ms": ms | None}}.
    A missing/empty history yields None so the tile can say "collecting…".
    """
    now = time.time()
    cutoff = now - _HISTORY_WINDOW_S
    try:
        with _HISTORY_LOCK:
            try:
                history = json.loads(_HISTORY_PATH.read_text())
                if not isinstance(history, dict):
                    history = {}
            except Exception:  # noqa: BLE001 - first run / corrupt file
                history = {}
            for result in results:
                samples = history.get(result["key"], [])
                samples.append([
                    int(now),
                    1 if result["status"] == "up" else 0,
                    result.get("ms"),
                ])
                samples = [s for s in samples if s[0] >= cutoff][-3000:]
                history[result["key"]] = samples
            _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = _HISTORY_PATH.with_suffix(".tmp")
            tmp.write_text(json.dumps(history))
            tmp.replace(_HISTORY_PATH)
    except Exception:  # noqa: BLE001 - history is a bonus, never break the page
        return {r["key"]: {"uptime24h": None, "avg_ms": None} for r in results}
    summary = {}
    for key, samples in history.items():
        if not samples:
            summary[key] = {"uptime24h": None, "avg_ms": None}
            continue
        ups = [s for s in samples if s[1] == 1]
        latencies = [s[2] for s in ups if s[2] is not None]
        summary[key] = {
            "uptime24h": round(100.0 * len(ups) / len(samples), 1),
            "avg_ms": round(sum(latencies) / len(latencies)) if latencies else None,
        }
    for result in results:
        summary.setdefault(result["key"], {"uptime24h": None, "avg_ms": None})
    return summary


# ============================================================
# HOST + BOT STATS (free — no extra logins)
# ============================================================

def _cpu_temp_c():
    try:
        zones = {}
        for temp_file in Path("/sys/class/thermal").glob("thermal_zone*/temp"):
            zone = temp_file.parent
            ztype = (zone / "type").read_text().strip()
            zones[ztype] = int(temp_file.read_text().strip()) / 1000.0
        if "x86_pkg_temp" in zones:
            return round(zones["x86_pkg_temp"], 1)
        if zones:
            return round(max(zones.values()), 1)
    except Exception:  # noqa: BLE001
        pass
    return None


def _host_stats():
    stats = {
        "load": None, "temp_c": None,
        "mem_used_gb": None, "mem_total_gb": None,
        "disk_used_gb": None, "disk_total_gb": None,
        "bot_uptime_s": None, "uptime_s": None,
    }
    try:
        with open("/proc/loadavg") as f:
            stats["load"] = f.read().split()[:3]
    except Exception:  # noqa: BLE001
        pass
    stats["temp_c"] = _cpu_temp_c()
    try:
        meminfo = {}
        with open("/proc/meminfo") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0].endswith(":"):
                    meminfo[parts[0][:-1]] = int(parts[1])
        total = meminfo.get("MemTotal")
        avail = meminfo.get("MemAvailable")
        if total and avail is not None:
            stats["mem_total_gb"] = round(total / 1024 / 1024, 1)
            stats["mem_used_gb"] = round((total - avail) / 1024 / 1024, 1)
    except Exception:  # noqa: BLE001
        pass
    try:
        usage = shutil.disk_usage("/")
        stats["disk_total_gb"] = round(usage.total / 1024 ** 3)
        stats["disk_used_gb"] = round(usage.used / 1024 ** 3)
    except Exception:  # noqa: BLE001
        pass
    try:
        with open("/proc/uptime") as f:
            stats["uptime_s"] = int(float(f.read().split()[0]))
    except Exception:  # noqa: BLE001
        pass
    try:
        out = subprocess.run(
            ["systemctl", "show", "kushbot",
             "--property=ActiveEnterTimestampMonotonic", "--value"],
            capture_output=True, text=True, timeout=5,
        )
        started_mono_us = int(out.stdout.strip())
        if started_mono_us:
            now_mono_us = time.clock_gettime(time.CLOCK_MONOTONIC) * 1_000_000
            stats["bot_uptime_s"] = max(
                0, int((now_mono_us - started_mono_us) / 1_000_000)
            )
    except Exception:  # noqa: BLE001
        pass
    return stats


def _bot_stats():
    """Live Discord numbers from the bridge. None when the bridge is
    unreachable or the bot is not ready."""
    try:
        from web.services import bridge

        info = bridge.status()
        return {
            "guilds": int(info.get("guild_count") or 0),
            "members": int(info.get("member_total") or 0),
            "latency_ms": info.get("latency_ms"),
        }
    except Exception:  # noqa: BLE001
        return None


# ============================================================
# CREDENTIAL-GATED LIVE NUMBERS (AdGuard + Portainer)
# ============================================================

def _adguard_stats():
    """Blocked/query counts for today. Needs ADGUARD_USER + ADGUARD_PASSWORD
    in the .env (the admin login from the AdGuard setup wizard)."""
    user = os.getenv("ADGUARD_USER")
    password = os.getenv("ADGUARD_PASSWORD")
    if not user or not password:
        return {
            "configured": False,
            "hint": "Add ADGUARD_USER + ADGUARD_PASSWORD to the bot .env "
                    "to see blocked counts.",
        }
    try:
        token = base64.b64encode(f"{user}:{password}".encode()).decode()
        req = urllib.request.Request(
            "http://127.0.0.1/control/stats",
            headers={"Authorization": f"Basic {token}"},
        )
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read())
        queries = int(data.get("num_dns_queries", 0))
        blocked = int(data.get("num_blocked_filtering", 0))
        return {
            "configured": True,
            "queries": queries,
            "blocked": blocked,
            "blocked_pct": round(100.0 * blocked / queries, 1) if queries else 0.0,
        }
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "error": str(exc)[:100]}


def _portainer_stats():
    """Container counts. Needs PORTAINER_API_KEY in the .env (create one
    in Portainer: your user menu -> Access tokens)."""
    api_key = os.getenv("PORTAINER_API_KEY")
    if not api_key:
        return {
            "configured": False,
            "hint": "Create an access token in Portainer (user menu -> "
                    "Access tokens) and add PORTAINER_API_KEY to the bot .env.",
        }
    try:
        req = urllib.request.Request(
            "https://127.0.0.1:9443/api/endpoints/1/docker/containers/json?all=1",
            headers={"X-API-Key": api_key},
        )
        with urllib.request.urlopen(req, timeout=3, context=_CTX) as resp:
            containers = json.loads(resp.read())
        running = sum(1 for c in containers if c.get("State") == "running")
        return {
            "configured": True,
            "running": running,
            "total": len(containers),
        }
    except Exception as exc:  # noqa: BLE001
        return {"configured": True, "error": str(exc)[:100]}


# ============================================================
# ADMIN GATE + CSRF (same shape as backups.py)
# ============================================================

def _is_admin():
    """Logged-in user holds the admin tier on a guild the bot is in.

    Mirrors backups._is_moderator: intersect the user's Discord guilds
    with the bot's own guilds first, so an admin of an unrelated server
    must not pass. Fails closed when the bot is unreachable or not ready.
    """
    if not session.get("user"):
        return False
    try:
        guilds = get_user_guilds() or []
    except Exception:  # noqa: BLE001
        return False
    try:
        from web.services import bridge

        bot_guild_ids = {str(gid) for gid in bridge.get_bot_guild_ids()}
    except Exception:  # noqa: BLE001
        return False
    for guild in guilds:
        gid = guild.get("id") if isinstance(guild, dict) else None
        if gid and str(gid) in bot_guild_ids and has_access(gid, "admin"):
            return True
    return False


def _require_admin():
    if not session.get("user"):
        abort(401)
    if not _is_admin():
        abort(403)


def _check_csrf():
    """Accept the header token (JSON callers) or the form field.

    Same shape as backups._check_csrf. Returns an error string, else None.
    """
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or request.form.get("csrf_token")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return "Invalid CSRF token."
    return None


# ============================================================
# ROUTES
# ============================================================

@server_home_api.get("/server-home")
@require_login
def server_home_page():
    _require_admin()
    host = request.host.rsplit(":", 1)[0]
    services = []
    for svc in SERVICES:
        if svc["port"] == 80:
            link = f"{svc['scheme']}://{host}/"
        else:
            link = f"{svc['scheme']}://{host}:{svc['port']}/"
        services.append({**svc, "link": link})
    return render_template(
        "server_home.html", services=services, host_info=_host_info()
    )


@server_home_api.get("/api/server-home/status")
@require_login
def server_home_status():
    _require_admin()
    results = _probe_all()
    summary = _record_probes(results)
    services = []
    extras = {}
    with ThreadPoolExecutor(max_workers=2) as pool:
        adguard_f = pool.submit(_adguard_stats)
        portainer_f = pool.submit(_portainer_stats)
        extras["adguard"] = adguard_f.result()
        extras["portainer"] = portainer_f.result()
    for result in results:
        merged = dict(result)
        merged.update(summary.get(result["key"], {}))
        if result["key"] in extras:
            merged["extra"] = extras[result["key"]]
        services.append(merged)
    return jsonify({
        "success": True,
        "services": services,
        "host": _host_info(),
        "host_stats": _host_stats(),
        "bot": _bot_stats(),
    })


def _schedule_website_restart(delay=1.0):
    """Exit this process with code 42 after a short delay.

    The delay lets the HTTP response leave first. Exit 42 is the
    restart code on both supervisors: the Windows watchdog relaunches
    on exit 42, and systemd Restart=on-failure relaunches on any
    non-zero exit. Exit 0 must never be used here (it stays stopped).
    os._exit, not sys.exit: a SystemExit raised inside a request
    handler would not stop the process. If the website was started
    plain (python run_web.py in a terminal, no watchdog/systemd),
    exit 42 just stops it — start it again by hand.
    """

    def _exit():
        print("[WEB] Restarting the website (exit 42).", flush=True)
        os._exit(42)

    timer = threading.Timer(delay, _exit)
    timer.daemon = True
    timer.start()


@server_home_api.post("/api/server-home/bot/restart")
@require_login
def bot_restart():
    """Restart the bot service. Admin-only, CSRF-checked.

    Restart-only on purpose: stopping the bot would kill the
    dashboard in the old single-process layout, and the restart
    button was never a stop button. The restart goes through the
    bridge (the bot exits 42 and its watchdog relaunches it); the
    website is a separate process and stays up. When the bridge is
    unreachable the button answers 503 instead of claiming a
    restart that never happens.
    """
    _require_admin()
    csrf_error = _check_csrf()
    if csrf_error:
        return jsonify({"success": False, "error": csrf_error}), 403
    try:
        from web.services import bridge

        bridge.restart_bot()
    except Exception as exc:  # noqa: BLE001
        return jsonify({
            "success": False,
            "error": "Bot is not reachable through the bridge: %s" % exc,
        }), 503
    return jsonify({
        "success": True,
        "message": "Restarting the bot — it will be back in about "
                   "30 seconds and this page will reload itself.",
    })


@server_home_api.post("/api/server-home/website/restart")
@require_login
def website_restart():
    """Restart the website process. Admin-only, CSRF-checked.

    The website exits 42 after the response goes out; the watchdog
    (Windows) or systemd (server, Restart=on-failure) brings it back
    in a few seconds, and the page polls until it answers again. If
    the website was started plain with no supervisor, exit 42 just
    stops it — start it again by hand.
    """
    _require_admin()
    csrf_error = _check_csrf()
    if csrf_error:
        return jsonify({"success": False, "error": csrf_error}), 403
    _schedule_website_restart()
    return jsonify({
        "success": True,
        "message": "Restarting the website — it will be back in a few seconds.",
    })


@server_home_api.post("/api/internal/website/restart")
def website_restart_internal():
    """Restart the website, called by the bot's /restart_web.

    Machine-to-machine: authenticated by the X-Bridge-Secret header
    against BRIDGE_SECRET from .env (the same secret the bridge uses,
    reversed direction). No session gate, no CSRF check — the secret
    header is the auth. Fails closed: missing/wrong secret -> 401,
    BRIDGE_SECRET unset -> 503, never restart.
    """
    secret = os.environ.get("BRIDGE_SECRET") or ""
    if not secret:
        return jsonify({
            "success": False,
            "error": "BRIDGE_SECRET is not configured.",
        }), 503
    supplied = request.headers.get("X-Bridge-Secret") or ""
    if not supplied or not secrets.compare_digest(supplied, secret):
        return jsonify({
            "success": False,
            "error": "Missing or invalid bridge secret.",
        }), 401
    _schedule_website_restart()
    return jsonify({"success": True})


def _host_info():
    info = {"bot_service": "unknown", "uptime": None, "load": None}
    try:
        out = subprocess.run(
            ["systemctl", "is-active", "kushbot"],
            capture_output=True, text=True, timeout=5,
        )
        info["bot_service"] = out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        pass
    try:
        with open("/proc/uptime") as f:
            info["uptime"] = int(float(f.read().split()[0]))
    except Exception:  # noqa: BLE001
        pass
    try:
        with open("/proc/loadavg") as f:
            info["load"] = f.read().split()[:3]
    except Exception:  # noqa: BLE001
        pass
    return info
