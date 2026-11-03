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
  cached in memory (self._cfg); every save updates the cache, so
  on_message never hits the database just to find the channel.
- Status lives in introduction_status (one row per guild+member).
- Every listener body is wrapped so one failure (missing role, no
  Manage Roles permission, a deleted channel) is logged and never
  kills the event flow or the rest of the bot.
- The bot's own role changes fire on_member_update too. The sync
  there only mirrors state (role present <-> introduced), which is
  idempotent, so the bot's own actions are harmless; the audit log
  is consulted best-effort only to name who made a manual change.
- No loops, no background tasks, no views, no modals, no VRChat.
"""

import traceback
from datetime import datetime

import discord
from discord.ext import commands

from config import GUILD_IDS
from data.DB.Storage.storage import (
    count_introduced,
    get_introduction_by_message_url,
    get_introduction_config,
    get_introduction_status,
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


class Introduction(commands.Cog):
    """Track member introductions: channel watch, role, scan, check."""

    def __init__(self, bot):
        self.bot = bot
        self._cfg = {}  # guild_id (str) -> config dict

    # ---------- config helpers ----------

    async def get_cfg(self, guild_id):
        gid = str(guild_id)
        if gid in self._cfg:
            return self._cfg[gid]
        try:
            cfg = await get_introduction_config(gid)
        except Exception as e:
            print(f"[INTRO] Could not load config for guild {gid}: {e!r}")
            cfg = {}
        merged = dict(DEFAULT_CONFIG)
        merged.update(cfg or {})
        self._cfg[gid] = merged
        return merged

    async def save_cfg(self, guild_id, **fields):
        """Merge fields into the cached config and persist the row."""
        gid = str(guild_id)
        cfg = await self.get_cfg(gid)
        cfg.update(fields)
        self._cfg[gid] = cfg
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

    @discord.slash_command(
        name="intro_set_channel",
        description="Set the introductions channel (and optional log channel).",
        guild_ids=GUILD_IDS,
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
        if not _is_manager(ctx):
            await ctx.respond(
                "You need Manage Server to set up introduction tracking.",
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

    @discord.slash_command(
        name="intro_set_role",
        description="Set the role given to members who post an introduction.",
        guild_ids=GUILD_IDS,
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
        if not _is_manager(ctx):
            await ctx.respond(
                "You need Manage Server to set up introduction tracking.",
                ephemeral=True,
            )
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

    @discord.slash_command(
        name="intro_settings",
        description="Show the introduction tracking setup for this server.",
        guild_ids=GUILD_IDS,
    )
    async def intro_settings(self, ctx):
        if not _is_manager(ctx):
            await ctx.respond(
                "You need Manage Server to view introduction settings.",
                ephemeral=True,
            )
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
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="intro_toggle",
        description="Turn an introduction tracking behaviour on or off.",
        guild_ids=GUILD_IDS,
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
        if not _is_manager(ctx):
            await ctx.respond(
                "You need Manage Server to change introduction settings.",
                ephemeral=True,
            )
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

    @discord.slash_command(
        name="intro_scan",
        description="Scan the intro channel and mark everyone who already posted.",
        guild_ids=GUILD_IDS,
    )
    async def intro_scan(
        self,
        ctx,
        limit: discord.Option(
            int,
            "How many recent messages to scan (1-1000)",
            required=False,
            default=100,
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
        if not _is_mod(ctx):
            await ctx.respond(
                "You need Manage Messages to scan introductions.",
                ephemeral=True,
            )
            return
        await ctx.defer(ephemeral=True)
        cfg = await self.get_cfg(ctx.guild.id)
        channel = self._get_text_channel(ctx.guild, cfg.get("channel_id"))
        if channel is None:
            await ctx.followup.send(
                "No intro channel is set (or it no longer exists). "
                "Set one with /intro_set_channel first.",
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
        newly = 0
        already = 0
        bots = 0
        role_given = 0
        role_failed = 0
        seen_counts = {}
        for msg in messages:
            author = msg.author
            if author.bot:
                bots += 1
                continue
            seen_counts[author.id] = seen_counts.get(author.id, 0) + 1
            try:
                row = await get_introduction_status(str(ctx.guild.id), str(author.id))
            except Exception as e:
                print(f"[INTRO] Intro lookup failed during scan: {e!r}")
                continue
            if row.get("has_introduced"):
                already += 1
                continue
            if not await self._mark_introduced(
                ctx.guild.id, author.id, msg.jump_url, msg.created_at
            ):
                continue
            newly += 1
            if add_role and cfg.get("auto_assign_role", True) and role is not None:
                member = author if isinstance(author, discord.Member) \
                    else ctx.guild.get_member(author.id)
                if member is not None:
                    if await self._set_role(
                        ctx.guild, member, role, True, "Introduction found by scan"
                    ):
                        role_given += 1
                    else:
                        role_failed += 1
        multi = sum(1 for c in seen_counts.values() if c > 1)
        embed = discord.Embed(
            title="Introduction scan complete",
            description=f"Scanned the last {len(messages)} messages in {channel.mention}.",
            color=discord.Color.blurple(),
        )
        embed.add_field(name="Newly marked", value=str(newly), inline=True)
        embed.add_field(name="Already had one", value=str(already), inline=True)
        embed.add_field(name="Bot messages skipped", value=str(bots), inline=True)
        embed.add_field(name="Roles given", value=str(role_given), inline=True)
        embed.add_field(name="Roles that failed", value=str(role_failed), inline=True)
        embed.add_field(
            name="Posted more than once",
            value=str(multi),
            inline=True,
        )
        await ctx.followup.send(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="intro_check",
        description="Check whether a member has posted an introduction.",
        guild_ids=GUILD_IDS,
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
        if not _is_mod(ctx):
            await ctx.respond(
                "You need Manage Messages to check introductions.",
                ephemeral=True,
            )
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

    @discord.user_command(name="Check Introduction", guild_ids=GUILD_IDS)
    async def check_introduction_ctx(self, ctx, member: discord.Member):
        if not _is_mod(ctx):
            await ctx.respond(
                "You need Manage Messages to check introductions.",
                ephemeral=True,
            )
            return
        await ctx.defer(ephemeral=True)
        cfg = await self.get_cfg(ctx.guild.id)
        embed, _found = await self._check_user(ctx.guild, cfg, member.id, member=member)
        await ctx.followup.send(embed=embed, ephemeral=True)

    # ---------- listeners (all guarded; never raise) ----------

    @commands.Cog.listener()
    async def on_message(self, message):
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
            if member is not None:
                assigned = await self._set_role(
                    message.guild, member, role, True, "Introduction posted"
                )
        embed = discord.Embed(
            title="Introduction posted",
            description=(
                f"{message.author.mention} posted their introduction: "
                f"[jump to message]({message.jump_url})"
            ),
            color=discord.Color.green(),
        )
        if role is not None:
            embed.add_field(
                name="Intro role",
                value=(
                    "Given"
                    if assigned
                    else "Could not be given — check the bot's permissions and role order."
                ),
                inline=True,
            )
        await self._log(message.guild, cfg, embed)

    @commands.Cog.listener()
    async def on_member_join(self, member):
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
        await self._set_role(
            member.guild, member, role, True,
            "Re-joined with an introduction on file",
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload):
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
        removed = None
        if role is not None and member is not None:
            removed = await self._set_role(
                guild, member, role, False, "Introduction message deleted"
            )
        embed = discord.Embed(
            title="Introduction removed",
            description=f"<@{row['user_id']}> deleted their introduction message.",
            color=discord.Color.orange(),
        )
        if role is not None and member is not None:
            embed.add_field(
                name="Intro role",
                value=(
                    "Removed"
                    if removed
                    else "Could not be removed — check the bot's permissions."
                ),
                inline=True,
            )
        await self._log(guild, cfg, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
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
        if added and row.get("has_introduced"):
            return
        if not added and not row.get("has_introduced"):
            return
        actor_name = "Someone"
        try:
            async for entry in guild.audit_logs(
                limit=5, action=discord.AuditLogAction.member_role_update
            ):
                if entry.target is not None and entry.target.id == after.id:
                    if entry.user is not None:
                        actor_name = entry.user.display_name
                    break
        except Exception:
            pass
        try:
            await save_introduction_status(str(guild.id), str(after.id), {
                "has_introduced": added,
                "introduced_at": row.get("introduced_at") if added else None,
                "message_url": row.get("message_url") or "",
            })
        except Exception as e:
            print(f"[INTRO] Could not sync intro status: {e!r}")
            return
        verb = "gave" if added else "took"
        embed = discord.Embed(
            title="Introduction status synced",
            description=(
                f"{actor_name} {verb} {after.mention} the intro role, "
                "so their introduction status now matches."
            ),
            color=discord.Color.blurple(),
        )
        await self._log(guild, cfg, embed)


def setup(bot):
    bot.add_cog(Introduction(bot))
