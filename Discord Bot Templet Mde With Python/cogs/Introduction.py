"""Introduction tracking cog (built 2026-11-02).

Ported from the Little Haven bot's introduction system (TypeScript /
Sapphire), adapted for this bot: every table is keyed by guild_id
because this bot is multi-guild and the Haven bot was single-guild,
and the Haven bot's custom module-permission system is deliberately
NOT ported -- gates here use this bot's normal Discord-permission
checks (Manage Server for setup, Manage Messages for lookups).

What it does, in plain terms: the server has an introductions
channel where new members post a hello. The bot watches that
channel, and when someone posts there for the first time it writes
down "this person introduced themselves, here is the message" and
gives them the introductions role. If they leave and come back, it
gives the role again. If they delete their introduction message, it
takes the role away and marks them as not introduced. Mods can also
scan the channel in bulk to catch everyone who already posted, and
check any member's introduction status.

Design notes (read before changing this file):
- Config lives in introduction_config (one row per guild) and is
  cached in memory (self._cfg) with a short TTL (_CFG_TTL), so
  on_message usually never hits the database just to find the
  channel -- but a setup change made by the other bot (the Helper
  owns /intro set_channel, set_role and toggle since the 2026-11-12
  command split, Option C) is picked up at most _CFG_TTL late, never
  only after a restart. Every save refreshes the cache at once, so
  the bot that saved sees its own change immediately.
- Status lives in introduction_status (one row per guild+member).
- Every listener body is wrapped so one failure (missing role, no
  Manage Roles permission, a deleted channel) is logged and never
  kills the event flow or the rest of the bot.
- The bot's own role changes fire on_member_update too, and like the
  Havenly bot they log a Manual embed naming the bot itself as
  moderator -- that is the original's behavior (its auto-assign shows
  up as both an Assigned embed and a Manual one, reason
  "Introduction role changed by the Havenly Bot"); the audit log is
  consulted best-effort only to name who made a manual change.
- The log embeds copy the Havenly bot's exactly (2026-11-09, Emily's
  screenshots + src/lib/commandEmbeds.ts and the listener sources in
  the LH backup repo): description text (not fields) for the
  Detected/Assigned/Marked/Scan/Delete embeds, the exact discord.js
  colors, a timestamp, and the "Powered by Havenly Bot" footer. The
  Manual embeds use fields (User/Moderator/Action inline, Reason
  below). Where the live bot and the backup code disagree on a title
  emoji (Assigned/Manual Added show a green heart live, a theatre
  mask in the backup), the live screenshots win.
- No loops, no background tasks, no views, no modals, no VRChat.
"""

import time
import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup

from config import GUILD_IDS, WORKER_MODE
from data.DB.Storage.storage import (
    count_introduced,
    get_introduction_by_message_url,
    get_introduction_config,
    get_introduction_status,
    get_introduction_statuses,
    save_introduction_config,
    save_introduction_status,
)

TOGGLE_SETTINGS = ("auto_assign_role", "auto_remove_role", "scan_on_message")
TOGGLE_LABELS = {
    "auto_assign_role": "Auto-assign intro role",
    "auto_remove_role": "Auto-remove role when intro deleted",
    "scan_on_message": "Watch the intro channel live",
}

DEFAULT_CONFIG = {
    "channel_id": "",
    "role_id": "",
    "log_channel_id": "",
    "auto_assign_role": True,
    "auto_remove_role": True,
    "scan_on_message": True,
    "scan_limit": 100,
}


# How long a loaded intro config is trusted before re-reading it
# from Postgres. The Helper owns the intro setup commands, so the
# main bot's listeners must pick up a Helper-made change without a
# restart; 60 s bounds that staleness while keeping on_message off
# the database for the common case. A failed load is cached only
# 10 s so a DB outage does not leave a stale config trusted.
_CFG_TTL = 60.0
_CFG_FAILURE_TTL = 10.0


def _is_manager(ctx):
    """Manage Server or Administrator (setup commands)."""
    if ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.manage_guild or perms.administrator)


def _is_mod(ctx):
    """Manage Messages or Administrator (lookup commands)."""
    if ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _log_user_line(user, user_id=None):
    """One user as the Havenly logs show them: `@Duke [xduke_br] (id)`.

    The mention renders the display name; the bracket holds the
    username; the id is in parens. When only an id is known (member
    left), fall back to a raw mention plus the id.
    """
    if user is not None:
        return f"{user.mention} [{user.name}] ({user.id})"
    return f"<@{user_id}> ({user_id})"


# The Havenly bot's exact log-embed colors (discord.js Colors.*).
HAVENLY_GREEN = 0x57F287
HAVENLY_BLUE = 0x3498DB
HAVENLY_YELLOW = 0xFEE75C
HAVENLY_RED = 0xED4245
HAVENLY_FOOTER = "Powered by Havenly Bot"


def _havenly_embed(title, color, description=None):
    """A log embed exactly as the Havenly bot builds it: the title, a
    description carrying the one-line facts, the exact discord.js
    color, a timestamp, and the "Powered by Havenly Bot" footer.
    (src/lib/commandEmbeds.ts in the LH backup repo, cross-checked
    against Emily's 2026-11-09 screenshots of the live bot.)
    """
    embed = discord.Embed(title=title, color=discord.Color(color),
                          description=description)
    embed.timestamp = datetime.now(timezone.utc)
    embed.set_footer(text=HAVENLY_FOOTER)
    return embed


def _format_full_dt(value):
    """A stored introduced_at as Discord's full-date stamp, or
    'Unknown'. The Havenly delete embed uses <t:...:F> for the
    original introduction date.
    """
    when = None
    if isinstance(value, datetime):
        when = value
    elif isinstance(value, str) and value:
        try:
            when = datetime.fromisoformat(value)
        except ValueError:
            when = None
    if when is None:
        return "Unknown"
    return discord.utils.format_dt(when, "F")


def _channel_usable(channel, member, need_send):
    """(ok, reason) -- can the bot actually use this channel?

    The intro channel needs read history (to scan it); the log
    channel needs send. A channel that was fine when it was set can
    go bad later (permissions changed, bot role moved), so this is
    checked both at set time and by /intro settings.
    """
    if channel is None or member is None:
        return False, "not found"
    try:
        perms = channel.permissions_for(member)
    except Exception:
        return False, "could not check its permissions"
    if not getattr(perms, "view_channel", True):
        return False, "the bot cannot see it"
    if need_send:
        if not getattr(perms, "send_messages", False):
            return False, "the bot cannot send messages there"
    else:
        if not getattr(perms, "read_message_history", False):
            return False, "the bot cannot read its history"
    return True, ""


def _role_usable(guild, role):
    """(ok, reason) -- can the bot assign this role right now?

    A role that was fine when it was set can end up above the bot's
    top role later (bot re-invited under a new identity, roles
    reordered), and then every assign silently fails.
    """
    if role is None:
        return False, "not set"
    me = guild.me
    if me is None:
        return False, "could not check (bot member not found)"
    if not getattr(me.guild_permissions, "manage_roles", False):
        return False, "the bot lacks the Manage Roles permission"
    if role.position >= me.top_role.position:
        return False, "it is above the bot's top role"
    return True, ""


# How long after a role change an audit-log entry can still be the
# record of that change. The gateway event fires within seconds of
# the change, so 120s (same window as admin_cog's timeout actor
# lookup) is generous without letting a stale entry from an earlier
# change match.
AUDIT_MATCH_WINDOW_SECONDS = 120


def _audit_role_ids(value):
    """Role ids from one side of an audit-log diff (Role / Object / dict)."""
    ids = set()
    for item in value or []:
        if isinstance(item, dict):
            rid = item.get("id")
        else:
            rid = getattr(item, "id", None)
        if rid is None:
            continue
        try:
            ids.add(int(rid))
        except (TypeError, ValueError):
            continue
    return ids


def _entry_matches_intro_change(entry, target_id, role_id, added, now=None):
    """True when an audit-log entry is the record of this intro-role change.

    All four must hold: the entry is a member_role_update, its target
    is the member, it was created within the match window, and the
    intro role is on the right side of the change (after.roles when
    the role was added, before.roles when it was removed). Pycord
    puts $add roles in changes.after.roles and $remove roles in
    changes.before.roles.
    """
    if entry is None:
        return False
    if getattr(entry, "action", None) is not discord.AuditLogAction.member_role_update:
        return False
    target = getattr(entry, "target", None)
    if target is None or getattr(target, "id", None) != target_id:
        return False
    created_at = getattr(entry, "created_at", None)
    if created_at is None:
        return False
    now = now or discord.utils.utcnow()
    try:
        age = (now - created_at).total_seconds()
    except Exception:
        return False
    if age > AUDIT_MATCH_WINDOW_SECONDS:
        return False
    changes = getattr(entry, "changes", None)
    if changes is None:
        return False
    side = getattr(changes, "after" if added else "before", None)
    return role_id in _audit_role_ids(getattr(side, "roles", None))


class Introduction(commands.Cog):
    """Track member introductions: channel watch, role, scan, check."""

    intro = SlashCommandGroup("intro", "Introduction tracking commands.", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        self._cfg = {}  # guild_id (str) -> config dict
        self._cfg_expires = {}  # guild_id (str) -> monotonic expiry

    # ---------- config helpers ----------

    async def get_cfg(self, guild_id):
        gid = str(guild_id)
        now = time.monotonic()
        if gid in self._cfg and now < self._cfg_expires.get(gid, 0):
            return self._cfg[gid]
        try:
            cfg = await get_introduction_config(gid)
        except Exception as e:
            print(f"[INTRO] Could not load config for guild {gid}: {e!r}")
            cfg = {}
            self._cfg[gid] = dict(DEFAULT_CONFIG)
            self._cfg_expires[gid] = now + _CFG_FAILURE_TTL
            return self._cfg[gid]
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg or {})
        self._cfg[gid] = merged
        self._cfg_expires[gid] = now + _CFG_TTL
        return merged

    async def save_cfg(self, guild_id, **fields):
        """Merge fields into the cached config and persist the row."""
        gid = str(guild_id)
        cfg = await self.get_cfg(gid)
        cfg.update(fields)
        self._cfg[gid] = cfg
        self._cfg_expires[gid] = time.monotonic() + _CFG_TTL
        await save_introduction_config(gid, {
            "channel_id": cfg.get("channel_id") or "",
            "role_id": cfg.get("role_id") or "",
            "log_channel_id": cfg.get("log_channel_id") or "",
            "auto_assign_role": bool(cfg.get("auto_assign_role", True)),
            "auto_remove_role": bool(cfg.get("auto_remove_role", True)),
            "scan_on_message": bool(cfg.get("scan_on_message", True)),
            "scan_limit": int(cfg.get("scan_limit") or 100),
        })
        return cfg

    # ---------- small helpers ----------

    def _get_text_channel(self, guild, channel_id):
        cid = _safe_int(channel_id)
        if cid is None:
            return None
        channel = guild.get_channel(cid)
        if isinstance(channel, discord.TextChannel):
            return channel
        return None

    def _intro_role(self, guild, cfg):
        rid = _safe_int(cfg.get("role_id"))
        if rid is None:
            return None
        return guild.get_role(rid)

    async def _set_role(self, guild, member, role, add, reason):
        """Best-effort role add/remove. Returns True when the member
        ends up in the wanted state (or was already there)."""
        if add and role in member.roles:
            return True
        if not add and role not in member.roles:
            return True
        me = guild.me
        if me is None or not me.guild_permissions.manage_roles:
            print(f"[INTRO] Cannot change intro role in guild {guild.id}: "
                  "bot lacks Manage Roles.")
            return False
        if role.position >= me.top_role.position:
            print(f"[INTRO] Cannot change intro role in guild {guild.id}: "
                  "role is above the bot's top role.")
            return False
        try:
            if add:
                await member.add_roles(role, reason=reason)
            else:
                await member.remove_roles(role, reason=reason)
            return True
        except discord.Forbidden:
            print(f"[INTRO] Forbidden changing intro role in guild {guild.id}.")
            return False
        except Exception:
            print(f"[INTRO] Failed changing intro role in guild {guild.id}:")
            traceback.print_exc()
            return False

    async def _mark_introduced(self, guild_id, user_id, message_url, when):
        """Save an introduction record. Returns True on success."""
        try:
            await save_introduction_status(str(guild_id), str(user_id), {
                "has_introduced": True,
                "introduced_at": when,
                "message_url": message_url or "",
            })
            return True
        except Exception as e:
            print(f"[INTRO] Could not save intro status for {user_id}: {e!r}")
            return False

    async def _log(self, guild, cfg, embed):
        channel = self._get_text_channel(guild, cfg.get("log_channel_id"))
        if channel is None:
            return
        try:
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[INTRO] Could not send log to channel "
                  f"{getattr(channel, 'id', '?')}: {e!r}")

    async def _find_in_history(self, guild, cfg, user_id, limit=100):
        """Search the intro channel's recent history for a message by
        user_id. Returns the message or None."""
        channel = self._get_text_channel(guild, cfg.get("channel_id"))
        if channel is None:
            return None
        try:
            async for msg in channel.history(limit=limit):
                if msg.author.id == int(user_id) and not msg.author.bot:
                    return msg
        except Exception as e:
            print(f"[INTRO] History scan failed for guild {guild.id}: {e!r}")
        return None

    async def _check_user(self, guild, cfg, user_id, member=None):
        """Look up a member's introduction status; if there is no
        record, scan the last 100 intro-channel messages and record
        a match. Returns (embed, found_bool)."""
        uid = str(user_id)
        row = {}
        try:
            row = await get_introduction_status(str(guild.id), uid)
        except Exception as e:
            print(f"[INTRO] Intro lookup failed: {e!r}")
        found = bool(row.get("has_introduced"))
        if not found:
            msg = await self._find_in_history(guild, cfg, uid, limit=100)
            if msg is not None:
                if await self._mark_introduced(guild.id, uid, msg.jump_url, msg.created_at):
                    found = True
                    row = {
                        "has_introduced": True,
                        "introduced_at": msg.created_at,
                        "message_url": msg.jump_url,
                    }
        display = member.display_name if member is not None else f"<@{uid}>"
        role = self._intro_role(guild, cfg)
        has_role = member is not None and role is not None and role in member.roles
        role_note = ""
        if found and member is not None and role is not None and not has_role \
                and cfg.get("auto_assign_role", True):
            if await self._set_role(guild, member, role, True, "Introduction on file"):
                has_role = True
                role_note = " (given now)"
        embed = discord.Embed(
            title=f"Introduction — {display}",
            color=discord.Color.green() if found else discord.Color.light_grey(),
        )
        embed.add_field(
            name="Status",
            value="Introduced" if found else "No introduction found",
            inline=True,
        )
        when = row.get("introduced_at")
        if found and when is not None:
            if isinstance(when, datetime):
                when_text = discord.utils.format_dt(when, "D")
            else:
                when_text = str(when)
        else:
            when_text = "—"
        embed.add_field(name="Introduced", value=when_text, inline=True)
        url = row.get("message_url") if found else ""
        embed.add_field(
            name="Message",
            value=f"[Jump to intro]({url})" if url else "—",
            inline=True,
        )
        if role is None:
            role_text = "No intro role set"
        elif has_role:
            role_text = f"Has {role.mention}{role_note}"
        else:
            role_text = f"Does not have {role.mention}{role_note}"
        embed.add_field(name="Intro role", value=role_text, inline=False)
        return embed, found

    # ---------- setup commands (Manage Server) ----------

    if WORKER_MODE:
        @intro.command(
            name="set_channel",
            description="Set the introductions channel (and optional log channel).",
        )
        async def intro_set_channel(
            self,
            ctx,
            channel: discord.Option(
                discord.TextChannel,
                "The channel where members post introductions",
                required=True,
            ),
            log_channel: discord.Option(
                discord.TextChannel,
                "Channel for intro log messages (optional)",
                required=False,
                default=None,
            ),
        ):
            from utils.permissions import check_slash_permission, _default_manage_or_admin
            if not await check_slash_permission(ctx, "intro_set_channel", _default_manage_or_admin):
                return
            # Validate the bot can actually use the channels before
            # saving them -- a log channel the bot cannot send in fails
            # silently later (only a console line), which is how the test
            # guild ended up with logs going nowhere (2026-11-09).
            me = ctx.guild.me
            ok, why = _channel_usable(channel, me, need_send=False)
            if not ok:
                await ctx.respond(
                    f"I can't use {channel.mention} as the intro channel: {why}.",
                    ephemeral=True,
                )
                return
            if log_channel is not None:
                ok, why = _channel_usable(log_channel, me, need_send=True)
                if not ok:
                    # Save the intro channel; the log channel stays as it
                    # was (a previously good one is not clobbered).
                    try:
                        await self.save_cfg(ctx.guild.id, channel_id=str(channel.id))
                    except Exception as e:
                        await ctx.respond(f"Could not save the intro channel: {e!r}", ephemeral=True)
                        return
                    await ctx.respond(
                        f"Intro channel set to {channel.mention}, but I did not save "
                        f"{log_channel.mention} as the log channel: {why}. "
                        "Give me access there and run this again.",
                        ephemeral=True,
                    )
                    return
            fields = {"channel_id": str(channel.id)}
            if log_channel is not None:
                fields["log_channel_id"] = str(log_channel.id)
            try:
                await self.save_cfg(ctx.guild.id, **fields)
            except Exception as e:
                await ctx.respond(f"Could not save the intro channel: {e!r}", ephemeral=True)
                return
            text = f"Intro channel set to {channel.mention}."
            if log_channel is not None:
                text += f" Intro logs will go to {log_channel.mention}."
            await ctx.respond(text, ephemeral=True)

    if WORKER_MODE:
        @intro.command(
            name="set_role",
            description="Set the role given to members who post an introduction.",
        )
        async def intro_set_role(
            self,
            ctx,
            role: discord.Option(
                discord.Role,
                "The role to give after an introduction",
                required=True,
            ),
        ):
            from utils.permissions import check_slash_permission, _default_manage_or_admin
            if not await check_slash_permission(ctx, "intro_set_role", _default_manage_or_admin):
                return
            if role.is_default():
                await ctx.respond(
                    "That is @everyone — pick a real role for introductions.",
                    ephemeral=True,
                )
                return
            if role.managed:
                await ctx.respond(
                    "That role is managed by an integration and the bot cannot assign it.",
                    ephemeral=True,
                )
                return
            me = ctx.guild.me
            if me is not None and role.position >= me.top_role.position:
                await ctx.respond(
                    "That role is above the bot's top role, so the bot could never assign it. "
                    "Move the bot's role higher or pick a lower role.",
                    ephemeral=True,
                )
                return
            if ctx.author.id != ctx.guild.owner_id \
                    and role.position >= ctx.author.top_role.position:
                await ctx.respond(
                    "That role is above your own top role, so you cannot hand it out.",
                    ephemeral=True,
                )
                return
            try:
                await self.save_cfg(ctx.guild.id, role_id=str(role.id))
            except Exception as e:
                await ctx.respond(f"Could not save the intro role: {e!r}", ephemeral=True)
                return
            await ctx.respond(
                f"Intro role set to {role.mention}. Members who post an introduction "
                "will get it automatically.",
                ephemeral=True,
            )

    if WORKER_MODE:
        @intro.command(
            name="settings",
            description="Show the introduction tracking setup for this server.",
        )
        async def intro_settings(self, ctx):
            from utils.permissions import check_slash_permission, _default_manage_or_admin
            if not await check_slash_permission(ctx, "intro_settings", _default_manage_or_admin):
                return
            cfg = await self.get_cfg(ctx.guild.id)
            try:
                count = await count_introduced(str(ctx.guild.id))
            except Exception:
                count = 0
            channel = self._get_text_channel(ctx.guild, cfg.get("channel_id"))
            role = self._intro_role(ctx.guild, cfg)
            log_channel = self._get_text_channel(ctx.guild, cfg.get("log_channel_id"))
            embed = discord.Embed(title="Introduction tracking", color=discord.Color.blurple())
            embed.add_field(
                name="Intro channel",
                value=channel.mention if channel else "Not set",
                inline=True,
            )
            embed.add_field(
                name="Intro role",
                value=role.mention if role else "Not set",
                inline=True,
            )
            embed.add_field(
                name="Log channel",
                value=log_channel.mention if log_channel else "Not set",
                inline=True,
            )
            embed.add_field(
                name="Watch the intro channel",
                value="On" if cfg.get("scan_on_message", True) else "Off",
                inline=True,
            )
            embed.add_field(
                name="Auto-assign role",
                value="On" if cfg.get("auto_assign_role", True) else "Off",
                inline=True,
            )
            embed.add_field(
                name="Auto-remove on delete",
                value="On" if cfg.get("auto_remove_role", True) else "Off",
                inline=True,
            )
            embed.add_field(
                name="Scan limit",
                value=str(cfg.get("scan_limit") or 100),
                inline=True,
            )
            embed.add_field(
                name="Members introduced",
                value=str(count),
                inline=True,
            )
            # Health checks: a channel or role that was fine when it was
            # set can go bad later (permissions changed, bot re-invited
            # under a new identity, roles reordered), and the intro flow
            # then fails silently -- the only trace was a console line.
            # Say so here, in Discord, where it can actually be seen.
            me = ctx.guild.me
            checks = []
            if channel is None:
                checks.append("❌ Intro channel: not set")
            else:
                ok, why = _channel_usable(channel, me, need_send=False)
                checks.append("✅ Intro channel: I can read it" if ok
                              else f"❌ Intro channel: {why}")
            if role is None:
                checks.append("❌ Intro role: not set")
            else:
                ok, why = _role_usable(ctx.guild, role)
                checks.append("✅ Intro role: I can assign it" if ok
                              else f"❌ Intro role: {why} — move it below my top role in Server Settings → Roles")
            if log_channel is None:
                checks.append("ℹ️ Log channel: not set (no intro logs will be posted)")
            else:
                ok, why = _channel_usable(log_channel, me, need_send=True)
                checks.append("✅ Log channel: I can send logs there" if ok
                              else f"❌ Log channel: {why} — give me access or pick another channel")
            embed.add_field(name="Checks", value="\n".join(checks), inline=False)
            await ctx.respond(embed=embed, ephemeral=True)

    if WORKER_MODE:
        @intro.command(
            name="toggle",
            description="Turn an introduction tracking behaviour on or off.",
        )
        async def intro_toggle(
            self,
            ctx,
            setting: discord.Option(
                str,
                "Which behaviour to change",
                required=True,
                choices=["auto_assign_role", "auto_remove_role", "scan_on_message"],
            ),
            value: discord.Option(
                bool,
                "On or off (leave blank to flip the current value)",
                required=False,
                default=None,
            ),
        ):
            from utils.permissions import check_slash_permission, _default_manage_or_admin
            if not await check_slash_permission(ctx, "intro_toggle", _default_manage_or_admin):
                return
            cfg = await self.get_cfg(ctx.guild.id)
            new_value = (not cfg.get(setting, True)) if value is None else bool(value)
            try:
                await self.save_cfg(ctx.guild.id, **{setting: new_value})
            except Exception as e:
                await ctx.respond(f"Could not save that setting: {e!r}", ephemeral=True)
                return
            await ctx.respond(
                f"{TOGGLE_LABELS[setting]} is now {'on' if new_value else 'off'}.",
                ephemeral=True,
            )

    # ---------- lookup commands (moderator) ----------

    if WORKER_MODE:
        @intro.command(
            name="scan",
            description="Scan the intro channel and mark everyone who already posted.",
        )
        async def intro_scan(
            self,
            ctx,
            limit: discord.Option(
                int,
                "How many recent messages to scan (1-1000, default 50)",
                required=False,
                default=50,
                min_value=1,
                max_value=1000,
            ),
            add_role: discord.Option(
                bool,
                "Also give the intro role to people found (default: yes)",
                required=False,
                default=True,
            ),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "intro_scan", _default_manage_messages_or_admin):
                return
            await ctx.defer(ephemeral=True)
            cfg = await self.get_cfg(ctx.guild.id)
            channel = self._get_text_channel(ctx.guild, cfg.get("channel_id"))
            if channel is None:
                await ctx.followup.send(
                    "No intro channel is set (or it no longer exists). "
                    "Set one with /intro set_channel first.",
                    ephemeral=True,
                )
                return
            role = self._intro_role(ctx.guild, cfg)
            try:
                messages = [m async for m in channel.history(limit=limit)]
            except discord.Forbidden:
                await ctx.followup.send(
                    "The bot cannot read the intro channel's history.",
                    ephemeral=True,
                )
                return
            except Exception as e:
                await ctx.followup.send(
                    f"Could not read the intro channel: {e!r}",
                    ephemeral=True,
                )
                return
            # P2-19: dedupe authors first, then ONE batch lookup for the
            # whole scan instead of one sequential lookup per message.
            # channel.history yields newest first, so the first message
            # seen for an author is their newest -- the same message the
            # old per-message loop would have recorded for them.
            first_msg = {}
            seen_counts = {}
            bots = 0
            for msg in messages:
                author = msg.author
                if author.bot:
                    bots += 1
                    continue
                seen_counts[author.id] = seen_counts.get(author.id, 0) + 1
                if author.id not in first_msg:
                    first_msg[author.id] = msg
            try:
                statuses = await get_introduction_statuses(
                    str(ctx.guild.id), list(first_msg))
            except Exception as e:
                print(f"[INTRO] Intro batch lookup failed during scan: {e!r}")
                await ctx.followup.send(
                    "Could not read the introduction records, so the scan "
                    "was aborted -- nothing was marked. Try again in a bit.",
                    ephemeral=True,
                )
                return
            newly = 0
            already = 0
            already_has_role = 0
            role_given = 0
            role_failed = 0
            repaired = 0
            for author_id, msg in first_msg.items():
                row = statuses.get(str(author_id), {})
                member = msg.author if isinstance(msg.author, discord.Member) \
                    else ctx.guild.get_member(author_id)
                has_role = member is not None and role is not None \
                    and role in member.roles
                if has_role:
                    # Already holds the intro role: record the intro in
                    # the DB and count them, but never try to add the role
                    # -- they already have it, and re-adding could
                    # disturb it.
                    if row.get("has_introduced"):
                        already += 1
                    elif await self._mark_introduced(
                        ctx.guild.id, author_id, msg.jump_url, msg.created_at
                    ):
                        newly += 1
                    else:
                        continue
                    already_has_role += 1
                    continue
                if row.get("has_introduced"):
                    # Has a record but lost the role: the Havenly scan
                    # hands it back (its skip rule is record AND role).
                    already += 1
                    if add_role and cfg.get("auto_assign_role", True) \
                            and role is not None and member is not None:
                        if await self._set_role(
                            ctx.guild, member, role, True, "Introduction found by scan"
                        ):
                            role_given += 1
                            repaired += 1
                        else:
                            role_failed += 1
                    continue
                if not await self._mark_introduced(
                    ctx.guild.id, author_id, msg.jump_url, msg.created_at
                ):
                    continue
                newly += 1
                if add_role and cfg.get("auto_assign_role", True) and role is not None:
                    if member is not None:
                        if await self._set_role(
                            ctx.guild, member, role, True, "Introduction found by scan"
                        ):
                            role_given += 1
                        else:
                            role_failed += 1
            # P3-5: add_role used to be silently ignored when auto-assign
            # was off (or no intro role was set) -- the scan reported
            # "Roles given: 0" with no hint why. The toggle stays the
            # gate (it is a Manage Server policy; the scan runs on Manage
            # Messages), but the reply now says so plainly.
            role_note = None
            if add_role and role is None:
                role_note = (
                    "No intro role is set, so no roles were given. "
                    "Set one with /intro set_role first."
                )
            elif add_role and not cfg.get("auto_assign_role", True):
                role_note = (
                    "Auto-assign intro role is off, so no roles were given. "
                    "Turn it on with /intro toggle auto_assign_role to let "
                    "scans hand out the role."
                )
            multi = sum(1 for c in seen_counts.values() if c > 1)
            embed = discord.Embed(
                title="Introduction scan complete",
                description=f"Scanned the last {len(messages)} messages "
                            f"({len(first_msg)} people) in {channel.mention}.",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Newly marked", value=str(newly), inline=True)
            embed.add_field(name="Already had one", value=str(already), inline=True)
            embed.add_field(name="Already has role", value=str(already_has_role), inline=True)
            embed.add_field(name="Bot messages skipped", value=str(bots), inline=True)
            embed.add_field(name="Roles given", value=str(role_given), inline=True)
            embed.add_field(name="Roles that failed", value=str(role_failed), inline=True)
            embed.add_field(
                name="Posted more than once",
                value=str(multi),
                inline=True,
            )
            if role_note is not None:
                embed.add_field(name="Role assignment", value=role_note, inline=False)
            await ctx.followup.send(embed=embed, ephemeral=True)
            # The Havenly bot also logs every scan to the log channel.
            # "New Introductions Found" counts every user the scan
            # (re-)marked -- newly found plus records whose role it
            # handed back -- the same shape the original's counter has
            # (it counts each user it marks, not just first-timers).
            log_channel = self._get_text_channel(ctx.guild, cfg.get("log_channel_id"))
            if log_channel is not None:
                scan_log = _havenly_embed(
                    "📝 Introduction Channel Scanned",
                    HAVENLY_GREEN,
                    f"**Channel:** {channel.mention}\n"
                    f"**Messages Processed:** {len(messages)}\n"
                    f"**New Introductions Found:** {newly + repaired}\n"
                    f"**Scanned by:** {ctx.author.mention} [{ctx.author.name}]",
                )
                try:
                    await log_channel.send(embed=scan_log)
                except Exception as e:
                    print(f"[INTRO] Could not send scan log: {e!r}")

    if not WORKER_MODE:
        @intro.command(
            name="check",
            description="Check whether a member has posted an introduction.",
        )
        async def intro_check(
            self,
            ctx,
            member: discord.Option(
                discord.Member,
                "The member to check",
                required=False,
                default=None,
            ),
            user_id: discord.Option(
                str,
                "Or a raw user ID (used when the member has left the server)",
                required=False,
                default=None,
            ),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "intro_check", _default_manage_messages_or_admin):
                return
            target_member = member
            target_id = None
            if target_member is not None:
                target_id = target_member.id
            elif user_id:
                parsed = _safe_int(user_id)
                if parsed is None:
                    await ctx.respond(
                        "That user ID does not look like a number.",
                        ephemeral=True,
                    )
                    return
                target_id = parsed
                target_member = ctx.guild.get_member(parsed)
            else:
                await ctx.respond(
                    "Pick a member or give a user ID to check.",
                    ephemeral=True,
                )
                return
            await ctx.defer(ephemeral=True)
            cfg = await self.get_cfg(ctx.guild.id)
            embed, _found = await self._check_user(
                ctx.guild, cfg, target_id, member=target_member
            )
            await ctx.followup.send(embed=embed, ephemeral=True)

    if not WORKER_MODE:
        @discord.user_command(name="Check Introduction", guild_ids=GUILD_IDS)
        async def check_introduction_ctx(self, ctx, member: discord.Member):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "intro_check_ctx", _default_manage_messages_or_admin):
                return
            await ctx.defer(ephemeral=True)
            cfg = await self.get_cfg(ctx.guild.id)
            embed, _found = await self._check_user(ctx.guild, cfg, member.id, member=member)
            await ctx.followup.send(embed=embed, ephemeral=True)

    # ---------- listeners (all guarded; never raise) ----------

    @commands.Cog.listener()
    async def on_message(self, message):
        # Main bot only: real-time intro detection + role assignment.
        # If the worker ran it too, every intro post would be marked
        # twice (two embeds, two role assignments).
        if WORKER_MODE:
            return
        try:
            await self._on_message(message)
        except Exception:
            print("[INTRO] on_message failed:")
            traceback.print_exc()

    async def _on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        cfg = await self.get_cfg(message.guild.id)
        if not cfg.get("scan_on_message", True):
            return
        channel_id = _safe_int(cfg.get("channel_id"))
        if channel_id is None or message.channel.id != channel_id:
            return
        try:
            row = await get_introduction_status(
                str(message.guild.id), str(message.author.id)
            )
        except Exception as e:
            print(f"[INTRO] Intro lookup failed: {e!r}")
            return
        if row.get("has_introduced"):
            return
        await self._mark_introduced(
            message.guild.id,
            message.author.id,
            message.jump_url,
            message.created_at,
        )
        role = self._intro_role(message.guild, cfg)
        assigned = None
        if cfg.get("auto_assign_role", True) and role is not None:
            member = message.author if isinstance(message.author, discord.Member) \
                else message.guild.get_member(message.author.id)
            if member is not None and role not in member.roles:
                assigned = await self._set_role(
                    message.guild, member, role, True, "Introduction posted"
                )
        # The Havenly embeds carry the facts in the description (not
        # fields), with the exact discord.js color, a timestamp, and
        # the "Powered by Havenly Bot" footer.
        detected = _havenly_embed(
            "👋 New Introduction Detected",
            HAVENLY_GREEN,
            f"**User:** {_log_user_line(message.author)}\n"
            f"**Channel:** {message.channel.mention}\n"
            f"**Message:** [View Introduction]({message.jump_url})",
        )
        await self._log(message.guild, cfg, detected)
        if assigned:
            assigned_embed = _havenly_embed(
                "💚 Introduction Role Assigned",
                HAVENLY_BLUE,
                f"**User:** {_log_user_line(message.author)}\n"
                f"**Role:** {role.mention} [{role.name}]\n"
                f"**Introduction:** [View Message]({message.jump_url})",
            )
            await self._log(message.guild, cfg, assigned_embed)
        elif role is None:
            # No role configured: the Havenly bot logs the intro as
            # "marked" instead of assigning anything.
            marked = _havenly_embed(
                "📝 User Marked as Introduced",
                HAVENLY_YELLOW,
                f"**User:** {_log_user_line(message.author)}\n"
                f"**Introduction:** [View Message]({message.jump_url})\n"
                "**Note:** No role configured for automatic assignment",
            )
            await self._log(message.guild, cfg, marked)

    @commands.Cog.listener()
    async def on_member_join(self, member):
        # Main bot only (see on_message above).
        if WORKER_MODE:
            return
        try:
            await self._on_member_join(member)
        except Exception:
            print("[INTRO] on_member_join failed:")
            traceback.print_exc()

    async def _on_member_join(self, member):
        cfg = await self.get_cfg(member.guild.id)
        if not cfg.get("auto_assign_role", True):
            return
        role = self._intro_role(member.guild, cfg)
        if role is None:
            return
        try:
            row = await get_introduction_status(str(member.guild.id), str(member.id))
        except Exception as e:
            print(f"[INTRO] Intro lookup failed: {e!r}")
            return
        if not row.get("has_introduced"):
            return
        if role in member.roles:
            return
        given = await self._set_role(
            member.guild, member, role, True,
            "Re-joined with an introduction on file",
        )
        if given:
            # The Havenly bot logs the re-join assignment with the
            # stored intro link and a "(User re-joined server)" note.
            # (Its code passes the literal string "introduction role"
            # as the role name here; the screenshots show the real
            # role name in the normal assignment embed, so the real
            # name is used.)
            url = row.get("message_url") or ""
            intro_line = f"[View Message]({url})" if url else "—"
            embed = _havenly_embed(
                "💚 Introduction Role Assigned",
                HAVENLY_BLUE,
                f"**User:** {_log_user_line(member)}\n"
                f"**Role:** {role.mention} [{role.name}]\n"
                f"**Introduction:** {intro_line} (User re-joined server)",
            )
            await self._log(member.guild, cfg, embed)

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
        # Main bot only (see on_message above).
        if WORKER_MODE:
            return
        try:
            await self._on_raw_message_delete(payload)
        except Exception:
            print("[INTRO] on_raw_message_delete failed:")
            traceback.print_exc()

    async def _on_raw_message_delete(self, payload):
        if payload.guild_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        cfg = await self.get_cfg(guild.id)
        if not cfg.get("auto_remove_role", True):
            return
        channel_id = _safe_int(cfg.get("channel_id"))
        if channel_id is None or payload.channel_id != channel_id:
            return
        url = (
            f"https://discord.com/channels/{payload.guild_id}/"
            f"{payload.channel_id}/{payload.message_id}"
        )
        try:
            row = await get_introduction_by_message_url(str(guild.id), url)
        except Exception as e:
            print(f"[INTRO] Intro lookup failed: {e!r}")
            return
        if not row or not row.get("has_introduced"):
            return
        member = guild.get_member(int(row["user_id"]))
        try:
            await save_introduction_status(str(guild.id), str(row["user_id"]), {
                "has_introduced": False,
                "introduced_at": None,
                "message_url": "",
            })
        except Exception as e:
            print(f"[INTRO] Could not clear intro status: {e!r}")
            return
        role = self._intro_role(guild, cfg)
        if role is not None and member is not None:
            await self._set_role(
                guild, member, role, False, "Introduction message deleted"
            )
        user = member if member is not None else self.bot.get_user(int(row["user_id"]))
        username = user.name if user is not None else "Unknown user"
        embed = _havenly_embed(
            "🗑️ Introduction Message Deleted",
            HAVENLY_RED,
            f"**{username}**'s introduction message was deleted",
        )
        embed.add_field(
            name="User",
            value=_log_user_line(member, row["user_id"]),
            inline=True,
        )
        embed.add_field(name="Action", value="❌ Introduction Removed", inline=True)
        embed.add_field(
            name="Original Introduction Date",
            value=_format_full_dt(row.get("introduced_at")),
            inline=True,
        )
        embed.add_field(
            name="Reason",
            value="Introduction message was deleted from the channel",
            inline=False,
        )
        await self._log(guild, cfg, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        # Main bot only (see on_message above).
        if WORKER_MODE:
            return
        try:
            await self._on_member_update(before, after)
        except Exception:
            print("[INTRO] on_member_update failed:")
            traceback.print_exc()

    async def _on_member_update(self, before, after):
        guild = after.guild
        cfg = await self.get_cfg(guild.id)
        role = self._intro_role(guild, cfg)
        if role is None:
            return
        before_ids = {r.id for r in before.roles}
        after_ids = {r.id for r in after.roles}
        if (role.id in before_ids) == (role.id in after_ids):
            return  # the intro role did not change
        added = role.id in after_ids
        try:
            row = await get_introduction_status(str(guild.id), str(after.id))
        except Exception as e:
            print(f"[INTRO] Intro lookup failed: {e!r}")
            return
        # No early return on the DB state: the Havenly listener logs
        # EVERY intro-role change (including the bot's own adds from
        # an intro post, a scan, or a re-join) and syncs the DB
        # idempotently; skipping when already in sync would hide
        # exactly those logs (its auto-assign shows up as both an
        # Assigned embed and a Manual one).
        actor = None
        audit_reason = None
        try:
            async for entry in guild.audit_logs(
                limit=10, action=discord.AuditLogAction.member_role_update
            ):
                if _entry_matches_intro_change(entry, after.id, role.id, added):
                    actor = getattr(entry, "user", None)
                    audit_reason = getattr(entry, "reason", None)
                    break
        except Exception:
            pass
        try:
            await save_introduction_status(str(guild.id), str(after.id), {
                "has_introduced": added,
                # The Havenly bot stamps a manual add with "now" (its
                # upsert passes a fresh date), it does not keep the
                # old introduction time.
                "introduced_at": datetime.now(timezone.utc) if added else None,
                "message_url": row.get("message_url") or "",
            })
        except Exception as e:
            print(f"[INTRO] Could not sync intro status: {e!r}")
            return
        # The Havenly bot logs EVERY intro-role change here, including
        # its own: its auto-assign shows up as an Assigned embed AND
        # a Manual one naming the bot itself as moderator, with the
        # reason "Introduction role changed by the Havenly Bot" (the
        # audit reason is overridden when the bot made the change).
        me = self.bot.user
        reason = audit_reason
        if actor is not None and me is not None and actor.id == me.id:
            reason = "Introduction role changed by the Havenly Bot"
        if not reason:
            reason = "Introduction role changed via Discord interface"
        if added:
            title = "💚 Manual Introduction Role Added"
            action = "✅ Role Added"
            color = HAVENLY_GREEN
        else:
            title = "❌ Manual Introduction Role Removed"
            action = "❌ Role Removed"
            color = HAVENLY_RED
        embed = _havenly_embed(
            title,
            color,
            f"**{after.name}**'s introduction role was "
            f"{'added' if added else 'removed'} manually",
        )
        embed.add_field(
            name="User", value=_log_user_line(after), inline=True)
        if actor is not None:
            moderator_line = _log_user_line(actor)
        else:
            moderator_line = ("<@MANUAL_ROLE_CHANGE> [System (Manual Role Change)] "
                              "(MANUAL_ROLE_CHANGE)")
        embed.add_field(
            name="Moderator", value=moderator_line, inline=True)
        embed.add_field(name="Action", value=action, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)
        await self._log(guild, cfg, embed)


def setup(bot):
    bot.add_cog(Introduction(bot))
