"""Sync HTTP client for the bot-side bridge (BRIDGE_CONTRACT.md section 4).

The website never logs into Discord and never imports discord.py. Every
live-Discord need goes through this client to the bot's bridge server on
localhost (default http://127.0.0.1:5001). One function per bridge
endpoint, same names as the paths.

Exceptions:
  BridgeUnavailable -- connection error / timeout / HTTP 503, or the
      BRIDGE_SECRET is not configured. Callers treat this as "bot is
      down": live pages degrade to 503, gates fail closed.
  BridgeError(status, message) -- 4xx/5xx passthrough (403 hierarchy
      refusal, 404 unknown guild/member, 400 bad input, ...).

Timeouts: reads 5 s, member-list 10 s, actions 20 s.
Caching: bot_is_ready() 5 s, get_bot_guild_ids() 60 s (fail-closed: on
error it returns []). Action results are never cached.
"""

import os
import time

import requests

try:
    from dotenv import load_dotenv

    load_dotenv()
except Exception:
    pass

BRIDGE_URL = os.environ.get("BRIDGE_URL", "http://127.0.0.1:5001").rstrip("/")
BRIDGE_VERSION = 1

READ_TIMEOUT = 5
MEMBER_LIST_TIMEOUT = 10
ACTION_TIMEOUT = 20

_READY_CACHE_S = 5
_GUILD_IDS_CACHE_S = 60

_secret_warned = False


class BridgeUnavailable(Exception):
    """The bridge cannot be reached, timed out, or is not ready (503)."""


class BridgeError(Exception):
    """The bridge answered with a 4xx/5xx that is not a 503."""

    def __init__(self, status, message):
        super().__init__(message or ("Bridge error %s" % status))
        self.status = status
        self.message = message or ("Bridge error %s" % status)


class BridgeDict(dict):
    """A bridge payload dict that also allows attribute access.

    Lets unmigrated call sites keep using ``guild.id`` / ``member.bot``
    / ``member.status`` while migrated code uses ``["id"]``. Both spell
    the same dict, so jsonify() still sees a plain dict.
    """

    def __getattr__(self, name):
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    def __setattr__(self, name, value):
        self[name] = value


def wrap(value):
    """Recursively convert bridge JSON dicts/lists into BridgeDicts."""
    if isinstance(value, dict):
        return BridgeDict({k: wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [wrap(v) for v in value]
    return value


def _secret():
    return os.environ.get("BRIDGE_SECRET") or None


def _headers():
    secret = _secret()
    if not secret:
        global _secret_warned
        if not _secret_warned:
            _secret_warned = True
            print("[ERROR] BRIDGE_SECRET is not set in .env; the bridge "
                  "cannot authenticate, so every live Discord call will "
                  "fail closed. Add BRIDGE_SECRET=<secret> to the bot .env "
                  "(same value the bot-side bridge uses).")
        raise BridgeUnavailable(
            "BRIDGE_SECRET is not set in .env; the bot bridge cannot be used."
        )
    return {"X-Bridge-Secret": secret}


def _request(method, path, timeout, params=None, json_body=None):
    url = BRIDGE_URL + path
    try:
        headers = _headers()
    except BridgeUnavailable:
        raise
    try:
        resp = requests.request(
            method, url, headers=headers,
            params=params, json=json_body, timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise BridgeUnavailable(
            "Bridge request timed out (%s %s): %r" % (method, path, exc)
        )
    except requests.exceptions.ConnectionError as exc:
        raise BridgeUnavailable(
            "Bridge is unreachable (%s %s): %r" % (method, path, exc)
        )
    except requests.exceptions.RequestException as exc:
        raise BridgeUnavailable(
            "Bridge request failed (%s %s): %r" % (method, path, exc)
        )
    try:
        payload = resp.json()
    except Exception:
        raise BridgeError(
            resp.status_code,
            "Bridge returned non-JSON (HTTP %s)" % resp.status_code,
        )
    if not isinstance(payload, dict):
        raise BridgeError(resp.status_code, "Bridge returned a bad envelope.")
    if resp.status_code == 503:
        raise BridgeUnavailable(payload.get("error") or "Bridge reports the bot is not ready.")
    if payload.get("success") is False or resp.status_code >= 400:
        raise BridgeError(
            resp.status_code, payload.get("error") or ("Bridge error %s" % resp.status_code)
        )
    return payload


def _get(path, timeout=READ_TIMEOUT, params=None):
    return _request("GET", path, timeout, params=params)


def _post(path, body, timeout=ACTION_TIMEOUT):
    return _request("POST", path, timeout, json_body=body or {})


def _member_payload(payload):
    """Actions return the updated member dict where one exists."""
    member = payload.get("member")
    if isinstance(member, dict):
        return wrap(member)
    return None


# ============================================================
# Reads
# ============================================================

def status():
    """GET /bridge/status -> {ready, user, latency_ms, guild_count,
    member_total, uptime_s, bridge_version}."""
    return _get("/bridge/status")


def get_guilds():
    """GET /bridge/guilds -> [guild dict, ...]."""
    return [wrap(g) for g in _get("/bridge/guilds").get("guilds") or []]


def get_guild(gid):
    """GET /bridge/guilds/{gid} -> guild dict, or None (404)."""
    try:
        return wrap(_get("/bridge/guilds/%s" % gid).get("guild"))
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_guild_dashboard(gid):
    """GET /bridge/guilds/{gid}/dashboard -> dashboard dict, or None (404)."""
    try:
        return _get("/bridge/guilds/%s/dashboard" % gid).get("dashboard")
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_channels(gid):
    """GET /bridge/guilds/{gid}/channels -> [channel dict, ...], or None (404)."""
    try:
        return [wrap(c) for c in _get("/bridge/guilds/%s/channels" % gid).get("channels") or []]
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_roles(gid):
    """GET /bridge/guilds/{gid}/roles -> [role dict, ...], or None (404)."""
    try:
        return [wrap(r) for r in _get("/bridge/guilds/%s/roles" % gid).get("roles") or []]
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_members(gid, limit=100, after=None, q=None):
    """GET /bridge/guilds/{gid}/members -> {members, next_after, total}."""
    params = {"limit": int(limit)}
    if after is not None:
        params["after"] = str(after)
    if q:
        params["q"] = q
    payload = _get(
        "/bridge/guilds/%s/members" % gid,
        timeout=MEMBER_LIST_TIMEOUT, params=params,
    )
    return {
        "members": [wrap(m) for m in payload.get("members") or []],
        "next_after": payload.get("next_after"),
        "total": payload.get("total"),
    }


def get_member(gid, uid):
    """GET /bridge/guilds/{gid}/members/{uid} -> member dict, or None (404)."""
    try:
        return wrap(_get("/bridge/guilds/%s/members/%s" % (gid, uid)).get("member"))
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_voice(gid):
    """GET /bridge/guilds/{gid}/voice -> [voice-channel dict, ...], or None (404)."""
    try:
        return [wrap(c) for c in _get("/bridge/guilds/%s/voice" % gid).get("channels") or []]
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


def get_bans(gid):
    """GET /bridge/guilds/{gid}/bans -> [{user, reason}, ...], or None (404)."""
    try:
        return [wrap(b) for b in _get("/bridge/guilds/%s/bans" % gid).get("bans") or []]
    except BridgeError as exc:
        if exc.status == 404:
            return None
        raise


# ============================================================
# Actions
# ============================================================

def timeout(gid, uid, seconds, reason=None):
    payload = _post(
        "/bridge/guilds/%s/members/%s/timeout" % (gid, uid),
        {"duration_seconds": int(seconds), "reason": reason},
    )
    return _member_payload(payload)


def untimeout(gid, uid, reason=None):
    payload = _post(
        "/bridge/guilds/%s/members/%s/untimeout" % (gid, uid),
        {"reason": reason},
    )
    return _member_payload(payload)


def kick(gid, uid, reason=None):
    payload = _post(
        "/bridge/guilds/%s/members/%s/kick" % (gid, uid),
        {"reason": reason},
    )
    return _member_payload(payload)


def ban(gid, uid, reason=None, delete_message_days=0):
    payload = _post(
        "/bridge/guilds/%s/members/%s/ban" % (gid, uid),
        {"reason": reason, "delete_message_days": int(delete_message_days)},
    )
    return _member_payload(payload)


def unban(gid, uid, reason=None):
    payload = _post(
        "/bridge/guilds/%s/members/%s/unban" % (gid, uid),
        {"reason": reason},
    )
    return _member_payload(payload)


def rename(gid, uid, nickname):
    payload = _post(
        "/bridge/guilds/%s/members/%s/rename" % (gid, uid),
        {"nickname": nickname},
    )
    return _member_payload(payload)


def strip_roles(gid, uid, reason=None):
    """Returns {removed: [...], skipped: [...]} (partial success)."""
    return _post(
        "/bridge/guilds/%s/members/%s/strip-roles" % (gid, uid),
        {"reason": reason},
    )


def purge(gid, cid, user_id=None, limit=100):
    """Returns {deleted: <int>}."""
    return _post(
        "/bridge/guilds/%s/channels/%s/purge" % (gid, cid),
        {"user_id": user_id, "limit": int(limit)},
    )


def send_dm(gid, uid, text):
    """Returns {sent: bool}."""
    return _post(
        "/bridge/guilds/%s/members/%s/dm" % (gid, uid),
        {"text": text},
    )


def award_xp(gid, uid, amount, display_name=None):
    """Returns {xp, level} as the bot's award_xp reports them."""
    return _post(
        "/bridge/guilds/%s/members/%s/xp" % (gid, uid),
        {"amount": amount, "display_name": display_name},
    )


def restart_bot():
    """POST /bridge/restart -- the bot replies, then exits 42."""
    return _post("/bridge/restart", {"confirm": "restart"})


# ============================================================
# Cached readiness / guild-list helpers
# ============================================================

_ready_cache = {"at": 0.0, "value": False}
_guild_ids_cache = {"at": 0.0, "value": []}


def bot_is_ready():
    """Cached 5 s. False when the bridge is down (fail closed)."""
    now = time.monotonic()
    if now - _ready_cache["at"] < _READY_CACHE_S:
        return _ready_cache["value"]
    try:
        value = bool(status().get("ready"))
    except (BridgeUnavailable, BridgeError):
        value = False
    _ready_cache["at"] = now
    _ready_cache["value"] = value
    return value


def get_bot_guild_ids():
    """Cached 60 s. Fail-closed: [] when the bridge is down."""
    now = time.monotonic()
    if now - _guild_ids_cache["at"] < _GUILD_IDS_CACHE_S:
        return list(_guild_ids_cache["value"])
    try:
        value = [str(g.get("id")) for g in get_guilds()]
    except (BridgeUnavailable, BridgeError):
        value = []
    _guild_ids_cache["at"] = now
    _guild_ids_cache["value"] = value
    return list(value)


def clear_cache():
    """Drop the readiness/guild-list caches (tests / reconnects)."""
    _ready_cache["at"] = 0.0
    _ready_cache["value"] = False
    _guild_ids_cache["at"] = 0.0
    _guild_ids_cache["value"] = []
