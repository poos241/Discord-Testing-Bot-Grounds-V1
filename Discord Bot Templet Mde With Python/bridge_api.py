"""Bot-side bridge API for the bot/website split.

See BRIDGE_CONTRACT.md (sections 2, 3, 7, 9). The standalone website
talks to the bot through this localhost-only aiohttp server; the bot
stays the single Discord actor and the website never logs into the
gateway.

Public surface:
    async def start_bridge(bot)  -- bind 127.0.0.1:BRIDGE_PORT (default
                                  5001), serve until stop_bridge().
    async def stop_bridge()      -- shut the server down cleanly.

Auth: every request must carry header ``X-Bridge-Secret`` equal to
``BRIDGE_SECRET`` from .env. If BRIDGE_SECRET is unset the bridge does
NOT start and the bot logs a loud [ERROR] with the exact .env line to
add. Do NOT auto-generate a secret.

Every response is JSON: {"success": true, ...} or
{"success": false, "error": "..."}. No handler does sync SQLite/file
work on the event loop (dashboard goes through asyncio.to_thread).
"""

import asyncio
import hmac
import os
import time
import traceback

import discord
from aiohttp import web

BRIDGE_VERSION = 1
_DEFAULT_PORT = 5001
_MAX_TIMEOUT_SECONDS = 28 * 24 * 60 * 60  # Discord's 28-day timeout cap

_bot = None
_runner = None
_stop_event = None
_started_at = None

# Exitable indirection so tests can stub the process exit without
# touching the real os._exit. A sys.exit() raised inside an event-loop
# task is swallowed by the loop and never terminates the process, so
# the restart path uses os._exit AFTER the gateway is cleanly closed.
_exit_process = os._exit


class _BridgeError(Exception):
    """An error that maps straight onto an HTTP status + message."""

    def __init__(self, status, message):
        super().__init__(message)
        self.status = status
        self.message = message


# ----------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------

def _ok(data=None, status=200):
    body = {"success": True}
    if data:
        body.update(data)
    return web.json_response(body, status=status)


def _fail(message, status):
    return web.json_response(
        {"success": False, "error": message}, status=status
    )


def _asset_url(asset):
    try:
        return str(asset.url) if asset else None
    except Exception:
        return None


def _parse_int(value, name):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise _BridgeError(400, "Invalid %s: %r." % (name, value))


async def _json_body(request):
    try:
        body = await request.json()
    except Exception:
        raise _BridgeError(400, "Request body must be valid JSON.")
    if not isinstance(body, dict):
        raise _BridgeError(400, "Request body must be a JSON object.")
    return body


def _require_ready():
    if _bot is None:
        raise _BridgeError(503, "Bot is not ready yet.")
    try:
        ready = _bot.is_ready()
    except Exception:
        ready = False
    if not ready:
        raise _BridgeError(503, "Bot is not ready yet.")


def _get_guild(gid_raw):
    """Guild the bot is in, or 404. gid_raw may be str or int."""
    gid = _parse_int(gid_raw, "guild id")
    guild = _bot.get_guild(gid)
    if guild is None:
        raise _BridgeError(404, "Guild not found (bot is not in it).")
    return guild


async def _resolve_member(guild, uid_raw):
    """Cache first, then fetch_member -- same as _get_member does today.

    404 when the user is not a member of the guild.
    """
    uid = _parse_int(uid_raw, "member id")
    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except discord.NotFound:
            raise _BridgeError(404, "Member not found in this guild.")
        except discord.Forbidden:
            raise _BridgeError(
                403, "The bot cannot look up that member."
            )
    if member is None:
        raise _BridgeError(404, "Member not found in this guild.")
    return member


def _member_dict(member):
    """MemberService.serialize_member + timed_out_until + permissions."""
    from web.services.member_service import MemberService

    data = MemberService(_bot).serialize_member(member)
    if data is None:
        return None
    try:
        until = getattr(member, "timed_out_until", None)
        data["timed_out_until"] = until.isoformat() if until else None
    except Exception:
        data["timed_out_until"] = None
    try:
        data["guild_permissions"] = int(member.guild_permissions.value)
    except Exception:
        data["guild_permissions"] = 0
    return data


def _guild_dict(guild):
    from web.services.server_service import ServerService

    return ServerService(_bot).serialize_guild(guild)


def _channel_dict(channel):
    """Channel dict for the bridge.

    ``type`` is the raw discord channel-type name (``text`` / ``voice`` /
    ``category`` / ``news`` / ``stage_voice`` / ``forum`` / ``*_thread``),
    so the website can count stage/forum channels and tell text from
    news -- the old text/voice/category/other mapping lumped them all
    under ``other``. The extra keys (category_id, created_at, mention,
    topic, slowmode_delay, nsfw, bitrate, user_limit) keep the
    website's channel-detail responses identical to the live-object
    versions. Every extra is getattr-guarded so test fakes without
    those attributes still serialise.
    """
    raw_type = getattr(channel, "type", None)
    if raw_type is not None:
        channel_type = str(raw_type)
    elif isinstance(channel, discord.TextChannel):
        channel_type = "text"
    elif isinstance(channel, discord.VoiceChannel):
        channel_type = "voice"
    elif isinstance(channel, discord.CategoryChannel):
        channel_type = "category"
    else:
        channel_type = "other"
    category = getattr(channel, "category", None)
    created_at = getattr(channel, "created_at", None)
    category_id = getattr(channel, "category_id", None)
    return {
        "id": str(channel.id),
        "name": channel.name,
        "type": channel_type,
        "position": getattr(channel, "position", 0),
        "category": category.name if category else None,
        "category_id": str(category_id) if category_id is not None else None,
        "created_at": created_at.isoformat() if created_at else None,
        "mention": "<#%s>" % channel.id,
        "topic": getattr(channel, "topic", None),
        "slowmode_delay": getattr(channel, "slowmode_delay", 0),
        "nsfw": bool(getattr(channel, "nsfw", False)),
        "bitrate": getattr(channel, "bitrate", None),
        "user_limit": getattr(channel, "user_limit", None),
    }


def _role_dict(role):
    return {
        "id": str(role.id),
        "name": role.name,
        "color": str(role.color),
        "position": role.position,
        "permissions": int(role.permissions.value),
        "managed": bool(role.managed),
        "mentionable": bool(role.mentionable),
        "hoist": bool(role.hoist),
    }


def _moderation():
    from web.services.moderation_service import ModerationService

    return ModerationService(_bot)


def _check_duration(duration):
    """Same bounds/messages as ModerationService.timeout."""
    if duration <= 0:
        raise _BridgeError(
            403, "Timeout duration must be greater than zero."
        )
    if duration > _MAX_TIMEOUT_SECONDS:
        raise _BridgeError(403, "Timeout cannot exceed 28 days.")


# ----------------------------------------------------------------------
# Middleware: auth on every route, JSON error envelope on every failure
# ----------------------------------------------------------------------

@web.middleware
async def _auth_middleware(request, handler):
    secret = os.getenv("BRIDGE_SECRET") or ""
    supplied = request.headers.get("X-Bridge-Secret") or ""
    if not secret or not hmac.compare_digest(supplied, secret):
        return _fail("Missing or invalid bridge secret.", 401)
    return await handler(request)


@web.middleware
async def _error_middleware(request, handler):
    try:
        return await handler(request)
    except _BridgeError as exc:
        return _fail(exc.message, exc.status)
    except discord.NotFound:
        return _fail("Not found.", 404)
    except discord.Forbidden:
        return _fail("The bot does not have permission to do that.", 403)
    except Exception as exc:
        # ModerationError (bot-hierarchy refusal, 28-day cap) -> 403.
        # Imported lazily here so this module never imports the
        # service layer at load time.
        try:
            from web.services.moderation_service import ModerationError
        except Exception:
            ModerationError = ()
        if isinstance(exc, ModerationError):
            return _fail(str(exc), 403)
        print("[ERROR] Bridge handler failed unexpectedly:")
        traceback.print_exc()
        return _fail("Internal bridge error.", 500)


# ----------------------------------------------------------------------
# Reads (GET)
# ----------------------------------------------------------------------

async def _status(request):
    ready = False
    user = None
    latency_ms = None
    guild_count = 0
    member_total = 0
    try:
        ready = bool(_bot is not None and _bot.is_ready())
    except Exception:
        ready = False
    if _bot is not None:
        try:
            latency_ms = round(float(_bot.latency or 0) * 1000, 2)
        except Exception:
            latency_ms = None
        try:
            guilds = list(_bot.guilds or [])
        except Exception:
            guilds = []
        guild_count = len(guilds)
        try:
            member_total = sum(
                int(getattr(g, "member_count", 0) or len(g.members))
                for g in guilds
            )
        except Exception:
            member_total = 0
        bot_user = getattr(_bot, "user", None)
        if bot_user is not None:
            user = {
                "id": str(bot_user.id),
                "name": bot_user.name,
                "avatar_url": _asset_url(
                    getattr(bot_user, "display_avatar", None)
                ),
            }
    uptime_s = round(time.monotonic() - _started_at, 1) if _started_at else 0
    return _ok({
        "ready": ready,
        "user": user,
        "latency_ms": latency_ms,
        "guild_count": guild_count,
        "member_total": member_total,
        "uptime_s": uptime_s,
        "bridge_version": BRIDGE_VERSION,
    })


async def _guilds(request):
    _require_ready()
    return _ok({"guilds": [_guild_dict(g) for g in list(_bot.guilds)]})


async def _guild(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    return _ok({"guild": _guild_dict(guild)})


async def _dashboard(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    # get_dashboard reads the Logger DB (sync sqlite) as today; keep
    # that work off the event loop like the timeout-board fix does.
    from web.services.server_service import ServerService

    dashboard = await asyncio.to_thread(
        ServerService(_bot).get_dashboard, int(guild.id)
    )
    if dashboard is None:
        raise _BridgeError(404, "Guild not found (bot is not in it).")
    return _ok({"dashboard": dashboard})


async def _channels(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    return _ok({
        "channels": [_channel_dict(c) for c in list(guild.channels)]
    })


async def _roles(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    return _ok({"roles": [_role_dict(r) for r in list(guild.roles)]})


async def _members(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    try:
        limit = int(request.query.get("limit", "100"))
    except ValueError:
        raise _BridgeError(400, "Invalid limit.")
    limit = max(1, min(500, limit))
    after_raw = request.query.get("after")
    after = None
    if after_raw is not None:
        after = _parse_int(after_raw, "after cursor")
    query = (request.query.get("q") or "").strip()

    if query:
        from web.services.member_service import MemberService

        members = MemberService(_bot).search_members(int(guild.id), query)
    else:
        members = list(guild.members)
    # Stable cursor order: ascending id, page after the last id seen.
    members = sorted(members, key=lambda m: m.id)
    total = len(members)
    if after is not None:
        members = [m for m in members if m.id > after]
    page = members[:limit]
    next_after = (
        str(page[-1].id) if len(members) > limit and page else None
    )
    return _ok({
        "members": [_member_dict(m) for m in page],
        "next_after": next_after,
        "total": total,
    })


async def _member(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    return _ok({"member": _member_dict(member)})


async def _voice(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    out = []
    for channel in getattr(guild, "voice_channels", []) or []:
        occupants = list(getattr(channel, "members", []) or [])
        if not occupants:
            continue
        out.append({
            "channel_id": str(channel.id),
            "channel_name": channel.name,
            "members": [_member_dict(m) for m in occupants],
        })
    return _ok({"channels": out})


async def _bans(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    try:
        entries = await guild.bans()
    except discord.Forbidden:
        raise _BridgeError(
            403, "The bot cannot list bans in this guild."
        )
    bans = []
    for entry in entries or []:
        user = entry.user
        bans.append({
            "user": {
                "id": str(user.id),
                "name": user.name,
                "avatar_url": _asset_url(
                    getattr(user, "display_avatar", None)
                ),
            },
            "reason": entry.reason,
        })
    return _ok({"bans": bans})


# ----------------------------------------------------------------------
# Actions (POST)
# ----------------------------------------------------------------------

async def _timeout(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    duration = body.get("duration_seconds")
    if isinstance(duration, bool) or not isinstance(duration, int):
        raise _BridgeError(
            400, "duration_seconds must be an integer (seconds)."
        )
    reason = body.get("reason")
    service = _moderation()
    # ModerationService semantics: bot-hierarchy check + 28-day cap.
    # (Its get_member is cache-only, so the resolved member above is
    # used for the Discord call instead of re-resolving.)
    service.can_moderate(guild, member)
    _check_duration(duration)
    from datetime import timedelta

    await member.timeout_for(
        timedelta(seconds=duration), reason=reason
    )
    return _ok({"member": _member_dict(member)})


async def _untimeout(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    service = _moderation()
    service.can_moderate(guild, member)
    await member.remove_timeout(reason=body.get("reason"))
    return _ok({"member": _member_dict(member)})


async def _kick(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    before = _member_dict(member)
    service = _moderation()
    service.can_moderate(guild, member)
    await member.kick(reason=body.get("reason"))
    return _ok({"member": before})


async def _ban(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    body = await _json_body(request)
    delete_days = body.get("delete_message_days", 0)
    if isinstance(delete_days, bool) or not isinstance(delete_days, int):
        raise _BridgeError(
            400, "delete_message_days must be an integer 0-7."
        )
    if delete_days < 0 or delete_days > 7:
        raise _BridgeError(
            400, "delete_message_days must be between 0 and 7."
        )
    uid = _parse_int(request.match_info["uid"], "member id")
    # Ban works on non-members too; only hierarchy-check when the
    # target is actually in the guild.
    member = guild.get_member(uid)
    if member is None:
        try:
            member = await guild.fetch_member(uid)
        except (discord.NotFound, discord.Forbidden):
            member = None
    before = _member_dict(member) if member else None
    if member is not None:
        _moderation().can_moderate(guild, member)
    await guild.ban(
        discord.Object(id=uid),
        reason=body.get("reason"),
        delete_message_days=delete_days,
    )
    return _ok({"member": before})


async def _unban(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    body = await _json_body(request)
    uid = _parse_int(request.match_info["uid"], "member id")
    await guild.unban(
        discord.Object(id=uid), reason=body.get("reason")
    )
    return _ok({})


async def _rename(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    if "nickname" not in body:
        raise _BridgeError(400, "nickname must not be empty.")
    nickname = body.get("nickname")
    if nickname is None:
        # Explicit null: reset. The website's rename route sends null
        # when the moderator clears a nickname (same as
        # member.edit(nick=None) did pre-split). A missing key is
        # still a 400 -- only an explicit null resets.
        await member.edit(nick=None)
        return _ok({"member": _member_dict(member)})
    if not isinstance(nickname, str) or not nickname:
        raise _BridgeError(400, "nickname must not be empty.")
    if len(nickname) > 32:
        raise _BridgeError(
            400, "Nickname must be 32 characters or fewer."
        )
    await member.edit(nick=nickname)
    return _ok({"member": _member_dict(member)})


async def _strip_roles(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    reason = body.get("reason")
    me = guild.me
    if me is None:
        raise _BridgeError(
            403, "The bot could not find itself in this guild."
        )
    removed = []
    skipped = []
    for role in list(member.roles):
        if role.name == "@everyone":
            continue
        if getattr(role, "managed", False):
            skipped.append({
                "id": str(role.id),
                "name": role.name,
                "reason": "Managed role (cannot be removed).",
            })
            continue
        try:
            if role >= me.top_role:
                skipped.append({
                    "id": str(role.id),
                    "name": role.name,
                    "reason": "Role is above the bot's highest role.",
                })
                continue
        except Exception:
            pass
        try:
            await member.remove_roles(role, reason=reason)
            removed.append({"id": str(role.id), "name": role.name})
        except (discord.Forbidden, discord.HTTPException) as exc:
            skipped.append({
                "id": str(role.id),
                "name": role.name,
                "reason": str(exc)[:120],
            })
    return _ok({
        "removed": removed,
        "skipped": skipped,
        "member": _member_dict(member),
    })


async def _purge(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    cid = _parse_int(request.match_info["cid"], "channel id")
    channel = guild.get_channel(cid)
    if channel is None:
        raise _BridgeError(404, "Channel not found in this guild.")
    if not callable(getattr(channel, "purge", None)):
        raise _BridgeError(400, "Channel is not a text channel.")
    body = await _json_body(request)
    limit = body.get("limit", 100)
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise _BridgeError(400, "limit must be an integer.")
    limit = max(1, min(1000, limit))
    user_id = body.get("user_id")
    check = None
    if user_id is not None:
        target = _parse_int(user_id, "user_id")
        check = lambda m: m.author.id == target  # noqa: E731
    deleted = await channel.purge(limit=limit, check=check)
    return _ok({"deleted": len(deleted)})


async def _dm(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    text = body.get("text")
    if not isinstance(text, str) or not text:
        raise _BridgeError(400, "text must not be empty.")
    try:
        from cogs.admin_cog import _dm_target
    except Exception:
        async def _dm_target(target, message):  # noqa: F811
            try:
                await target.send(message)
                return True
            except Exception:
                return False
    sent = await _dm_target(member, text)
    return _ok({"sent": bool(sent)})


async def _xp(request):
    _require_ready()
    guild = _get_guild(request.match_info["gid"])
    member = await _resolve_member(guild, request.match_info["uid"])
    body = await _json_body(request)
    amount = body.get("amount")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise _BridgeError(400, "amount must be an integer.")
    amount = max(-1000, min(1000, amount))
    display_name = body.get("display_name") or member.display_name
    from cogs.Level_system import award_xp

    gained = await award_xp(
        guild, member.id, display_name, amount, apply_event=False
    )
    from data.DB.Storage.storage import get_levels

    db = await get_levels(str(guild.id))
    record = (db or {}).get(str(member.id), {}) or {}
    return _ok({
        "xp": record.get("xp", 0),
        "level": record.get("level", 1),
        "levels_gained": list(gained or []),
    })


async def _restart(request):
    body = await _json_body(request)
    if body.get("confirm") != "restart":
        raise _BridgeError(
            400, 'confirm must be "restart".'
        )

    async def _delayed_restart():
        # Let the HTTP response flush before the gateway closes.
        await asyncio.sleep(0.5)
        try:
            await _bot.close()
        except Exception:
            pass
        # os._exit: a sys.exit() raised in an event-loop task is
        # swallowed by the loop and never ends the process; the
        # gateway is already closed at this point, so exiting here
        # is clean. 42 tells the watchdog to relaunch the bot.
        _exit_process(42)

    asyncio.create_task(_delayed_restart())
    return _ok({})


async def _not_found(request):
    return _fail("Unknown bridge endpoint.", 404)


# ----------------------------------------------------------------------
# Server lifecycle
# ----------------------------------------------------------------------

def _build_app():
    app = web.Application(
        middlewares=[_auth_middleware, _error_middleware]
    )
    app.router.add_get("/bridge/status", _status)
    app.router.add_get("/bridge/guilds", _guilds)
    app.router.add_get("/bridge/guilds/{gid}", _guild)
    app.router.add_get("/bridge/guilds/{gid}/dashboard", _dashboard)
    app.router.add_get("/bridge/guilds/{gid}/channels", _channels)
    app.router.add_get("/bridge/guilds/{gid}/roles", _roles)
    app.router.add_get("/bridge/guilds/{gid}/members", _members)
    app.router.add_get("/bridge/guilds/{gid}/members/{uid}", _member)
    app.router.add_get("/bridge/guilds/{gid}/voice", _voice)
    app.router.add_get("/bridge/guilds/{gid}/bans", _bans)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/timeout", _timeout)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/untimeout", _untimeout)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/kick", _kick)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/ban", _ban)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/unban", _unban)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/rename", _rename)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/strip-roles", _strip_roles)
    app.router.add_post("/bridge/guilds/{gid}/channels/{cid}/purge", _purge)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/dm", _dm)
    app.router.add_post("/bridge/guilds/{gid}/members/{uid}/xp", _xp)
    app.router.add_post("/bridge/restart", _restart)
    # JSON 404 for anything else under /bridge (and elsewhere).
    app.router.add_route("*", "/{tail:.*}", _not_found)
    return app


async def start_bridge(bot):
    """Start the bridge server; block until stop_bridge() is called.

    Returns True while serving, False when the bridge did not start
    (disabled, no secret, bad port, bind failure). Never raises for
    those cases: the bot must keep running and the website degrades.
    """
    global _bot, _runner, _stop_event, _started_at
    _bot = bot
    if os.getenv("BRIDGE_ENABLED", "1").lower() in ("0", "false", "no"):
        print("[INFO] Bridge API disabled (BRIDGE_ENABLED=0).")
        return False
    if not os.getenv("BRIDGE_SECRET"):
        print("[ERROR] Bridge API will NOT start: BRIDGE_SECRET is not set.")
        print("[ERROR] Add this line to .env (next to bot.py) and restart the bot:")
        print("[ERROR] BRIDGE_SECRET=<a long random secret shared with the website>")
        return False
    try:
        port = int(os.getenv("BRIDGE_PORT", str(_DEFAULT_PORT)))
    except ValueError:
        print("[ERROR] Bridge API will NOT start: BRIDGE_PORT is not a number.")
        return False
    app = _build_app()
    _stop_event = asyncio.Event()
    _started_at = time.monotonic()
    runner = web.AppRunner(app)
    try:
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", port)
        await site.start()
    except OSError as exc:
        print(
            "[ERROR] Bridge API could not bind 127.0.0.1:%d: %r" % (port, exc)
        )
        print("[ERROR] The bot will keep running; the website will degrade to 503s.")
        await runner.cleanup()
        return False
    _runner = runner
    print(
        "[OK] Bridge API listening on http://127.0.0.1:%d (localhost only)"
        % port
    )
    try:
        await _stop_event.wait()
    finally:
        await runner.cleanup()
        _runner = None
    return True


async def stop_bridge():
    """Stop the bridge server started by start_bridge()."""
    if _stop_event is not None:
        _stop_event.set()
