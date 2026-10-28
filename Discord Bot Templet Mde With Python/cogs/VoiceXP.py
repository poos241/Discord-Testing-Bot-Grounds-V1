# cogs/VoiceXP.py
"""Voice time XP + VC leaderboard (built 2026-10-28).

Opt-in XP for time spent in voice channels, on top of the existing
level/XP system (award_xp from cogs/Level_system.py), plus a
/voicexp leaderboard ranked by total voice time.

How it accrues (see /voicexp status and /voicexp config for the live
values):
  - A 1-minute ticker scans every voice channel the bot can see.
  - A member earns 1 minute only when ALL of these hold for that
    minute: they opted in (/voicexp optin), they are in a voice
    channel that is not the server AFK channel, they are not muted
    or deafened (self or server), and at least one other non-bot
    person is in the same channel.
  - Minutes are banked and converted to XP in chunks of 5 (so a
    3-minute chat still pays out when the member leaves voice, via
    the flush in on_voice_state_update).
  - Daily cap: each member can earn at most daily_cap_xp base XP
    per UTC day (default 100). The cap counts base XP before any
    active XP-event multiplier (award_xp still multiplies, so an
    event can push awarded XP past the cap — the cap itself is on
    base XP, matching how message XP is capped nowhere and event
    XP is a bonus on top).
  - Server-wide kill switch: /voicexp disable stops all accrual
    until /voicexp enable. Per-user opt-out (/voicexp optout) stops
    it for that user only and discards their unbanked minutes.
  - Stage channels do not count (only guild.voice_channels are
    scanned); a suppressed listener would not qualify anyway.
  - Pending (unbanked, under-5-minute) minutes live only in memory
    and are lost on a bot restart. Banked minutes/XP live in the
    voice_xp_users table and survive restarts.

Tables: voice_xp_config + voice_xp_users in data/DB/models.py.
Storage helpers live in data/DB/Storage/storage.py. New tables only
-- create_all() creates them on the next bot boot and never alters
an existing table.
"""
import time

import discord
from discord.ext import commands, tasks
from discord.commands import SlashCommandGroup

from config import admin_required, extra_help, GUILD_IDS
from data.DB.db import database
from data.DB.Storage.storage import (
    get_voice_xp_config,
    save_voice_xp_config,
    get_voice_xp_user,
    save_voice_xp_user,
    list_voice_xp_users,
    list_voice_xp_top,
)
from cogs.Level_system import award_xp

# Defaults for a server that has never run /voicexp setrate/setcap.
VOICE_XP_DEFAULT_RATE = 1      # XP per qualifying minute
VOICE_XP_DEFAULT_DAILY_CAP = 100  # base XP per user per UTC day (0 = no cap)
VOICE_XP_AWARD_CHUNK = 5       # bank minutes, award XP every this many
VOICE_XP_MIN_HUMANS = 2        # member + at least 1 other non-bot person


def _today_str():
    """UTC calendar day, YYYY-MM-DD. The daily cap resets on this."""
    return time.strftime("%Y-%m-%d", time.gmtime())


def _fmt_minutes(total):
    """'125' -> '2h 5m'; '45' -> '45m'; '0' -> '0m'."""
    total = int(total)
    hours, mins = divmod(total, 60)
    if hours:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def _cap_text(cap):
    return "no cap" if not cap else f"{cap} XP/day"


class VoiceXP(commands.Cog):
    """Voice time XP + VC leaderboard."""

    voicexp = SlashCommandGroup("voicexp", "Voice time XP", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> unbanked qualifying minutes (< AWARD_CHUNK).
        self._pending = {}
        self.voice_tick.start()

    # ---------- internals ----------

    async def _award_minutes(self, guild, member, minutes, cfg, row):
        """Bank `minutes` of voice time into the row and award XP for
        them, respecting the daily cap. Returns the base XP awarded
        (0 when the cap is already hit)."""
        if minutes <= 0:
            return 0
        gid, uid = str(guild.id), str(member.id)
        rate = cfg.get("xp_per_minute", VOICE_XP_DEFAULT_RATE) or VOICE_XP_DEFAULT_RATE
        cap = cfg.get("daily_cap_xp", VOICE_XP_DEFAULT_DAILY_CAP)
        today = _today_str()
        if row.get("xp_day") != today:
            row["xp_today"] = 0
            row["xp_day"] = today
        if cap:
            remaining = max(0, int(cap) - int(row.get("xp_today", 0)))
            base = min(int(minutes) * int(rate), remaining)
        else:
            base = int(minutes) * int(rate)
        row["total_minutes"] = int(row.get("total_minutes", 0)) + int(minutes)
        row["display_name"] = member.display_name
        if base > 0:
            row["total_voice_xp"] = int(row.get("total_voice_xp", 0)) + base
            row["xp_today"] = int(row.get("xp_today", 0)) + base
            # fallback_channel=None: level-ups announce only in the
            # configured level-up channel, if one is set.
            await award_xp(guild, member.id, member.display_name, base,
                           fallback_channel=None)
        await save_voice_xp_user(gid, uid, row)
        return base

    async def _flush_pending(self, guild, member):
        """Pay out a member's unbanked minutes (e.g. they left voice).
        Drops them silently when voice XP is disabled or they opted
        out, since those minutes no longer qualify."""
        gid, uid = str(guild.id), str(member.id)
        pending = self._pending.pop((gid, uid), 0)
        if pending <= 0:
            return
        cfg = await get_voice_xp_config(gid)
        if not cfg.get("enabled", True):
            return
        row = await get_voice_xp_user(gid, uid)
        if not row.get("opted_in"):
            return
        await self._award_minutes(guild, member, pending, cfg, row)

    async def _tick_guild(self, guild):
        cfg = await get_voice_xp_config(str(guild.id))
        if not cfg.get("enabled", True):
            return
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        for channel in guild.voice_channels:
            if channel.id == afk_id:
                continue  # sitting in AFK never counts
            humans = [m for m in channel.members if not m.bot]
            if len(humans) < VOICE_XP_MIN_HUMANS:
                continue  # need at least 1 other non-bot person
            for member in humans:
                vs = member.voice
                if vs is None or vs.channel is None or vs.channel.id != channel.id:
                    continue
                if vs.self_mute or vs.self_deaf or vs.mute or vs.deaf or vs.suppress:
                    continue  # muted/deafened minutes never count
                gid, uid = str(guild.id), str(member.id)
                row = await get_voice_xp_user(gid, uid)
                if not row.get("opted_in"):
                    continue
                pending = self._pending.get((gid, uid), 0) + 1
                if pending >= VOICE_XP_AWARD_CHUNK:
                    await self._award_minutes(guild, member, pending, cfg, row)
                    pending = 0
                self._pending[(gid, uid)] = pending

    # ---------- scheduler ----------

    @tasks.loop(minutes=1)
    async def voice_tick(self):
        for guild in self.bot.guilds:
            try:
                await self._tick_guild(guild)
            except Exception as e:
                print(f"[VoiceXP] Tick failed for guild {guild.id}: {e!r}")

    @voice_tick.before_loop
    async def before_voice_tick(self):
        await self.bot.wait_until_ready()
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[VoiceXP] DB connect check failed: {e!r}")

    # ---------- voice state events ----------

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if member.bot:
            return
        if before.channel is None:
            return  # joined voice; the ticker picks them up next minute
        if after.channel is not None and after.channel.id == before.channel.id:
            return  # mute/unmute/stream toggle: ticker re-evaluates each minute
        # Left voice, moved channels, or moved into the AFK channel:
        # pay out whatever is banked so far instead of waiting for a
        # full 5-minute chunk.
        try:
            await self._flush_pending(member.guild, member)
        except Exception as e:
            print(f"[VoiceXP] Flush failed for {member.id}: {e!r}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Gone from the server: drop unbanked minutes, don't award.
        self._pending.pop((str(member.guild.id), str(member.id)), None)

    # ---------- member commands ----------

    @voicexp.command(name="optin", description="Opt in to earning XP for time in voice channels.")
    @extra_help("You only earn voice XP after opting in. Requires at least 1 other non-bot person in the channel, and muted/deafened/AFK time never counts.")
    async def voicexp_optin(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        gid, uid = str(ctx.guild.id), str(ctx.user.id)
        row = await get_voice_xp_user(gid, uid)
        row["opted_in"] = True
        row["display_name"] = ctx.user.display_name
        await save_voice_xp_user(gid, uid, row)
        cfg = await get_voice_xp_config(gid)
        if not cfg.get("enabled", True):
            return await ctx.respond(
                "You are opted in, but voice XP is currently disabled for this server — "
                "an admin can turn it back on with /voicexp enable.", ephemeral=True)
        rate = cfg.get("xp_per_minute", VOICE_XP_DEFAULT_RATE)
        cap = cfg.get("daily_cap_xp", VOICE_XP_DEFAULT_DAILY_CAP)
        await ctx.respond(
            f"You are opted in to voice XP! You earn **{rate} XP per minute** in voice "
            f"(up to {_cap_text(cap)}), as long as someone else is in the channel with you "
            f"and you are not muted, deafened, or AFK.", ephemeral=True)

    @voicexp.command(name="optout", description="Opt out of voice XP (keeps your banked totals).")
    @extra_help("Stops future voice XP. Banked minutes/XP stay on the leaderboard; opt back in anytime.")
    async def voicexp_optout(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        gid, uid = str(ctx.guild.id), str(ctx.user.id)
        self._pending.pop((gid, uid), None)
        row = await get_voice_xp_user(gid, uid)
        if not row.get("opted_in"):
            return await ctx.respond("You are not opted in to voice XP.", ephemeral=True)
        row["opted_in"] = False
        row["display_name"] = ctx.user.display_name
        await save_voice_xp_user(gid, uid, row)
        await ctx.respond("You are opted out of voice XP. Your banked totals stay on the leaderboard.",
                          ephemeral=True)

    @voicexp.command(name="status", description="Show your (or another member's) voice XP stats.")
    @extra_help("Shows opt-in state, total voice time, total voice XP, and today's progress toward the daily cap.")
    async def voicexp_status(self, ctx, member: discord.Member = None):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        target = member or ctx.user
        gid, uid = str(ctx.guild.id), str(target.id)
        row = await get_voice_xp_user(gid, uid)
        cfg = await get_voice_xp_config(gid)
        rate = cfg.get("xp_per_minute", VOICE_XP_DEFAULT_RATE)
        cap = cfg.get("daily_cap_xp", VOICE_XP_DEFAULT_DAILY_CAP)
        today = _today_str()
        xp_today = int(row.get("xp_today", 0)) if row.get("xp_day") == today else 0
        embed = discord.Embed(title=f"Voice XP — {target.display_name}",
                              color=discord.Color.blurple())
        state = "Opted in" if row.get("opted_in") else "Not opted in"
        if not cfg.get("enabled", True):
            state += " (voice XP disabled server-wide)"
        embed.add_field(name="Status", value=state, inline=False)
        embed.add_field(name="Total voice time", value=_fmt_minutes(row.get("total_minutes", 0)), inline=True)
        embed.add_field(name="Total voice XP", value=f"{int(row.get('total_voice_xp', 0)):,} XP", inline=True)
        cap_txt = "no cap" if not cap else f"{xp_today:,} / {cap:,} XP"
        embed.add_field(name="Today", value=cap_txt, inline=True)
        embed.set_footer(text=f"Rate: {rate} XP/minute · banked in {VOICE_XP_AWARD_CHUNK}-minute chunks")
        await ctx.respond(embed=embed, ephemeral=(member is None))

    @voicexp.command(name="leaderboard", description="Show the voice time leaderboard.")
    @extra_help("Top 10 by total qualifying voice time, with total voice XP. Your own rank is shown if you are outside the top 10.")
    async def voicexp_leaderboard(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        gid, me = str(ctx.guild.id), str(ctx.user.id)
        top = await list_voice_xp_top(gid, limit=10)
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, row in enumerate(top, 1):
            member = ctx.guild.get_member(int(row["user_id"]))
            name = member.display_name if member else row.get("display_name") or f"User ID {row['user_id']}"
            pos = medals[i - 1] if i <= 3 else f"`{i}.`"
            you = " ⬅ you" if row["user_id"] == me else ""
            lines.append(f"{pos} **{name}** — {_fmt_minutes(row.get('total_minutes', 0))} "
                         f"· {int(row.get('total_voice_xp', 0)):,} voice XP{you}")
        embed = discord.Embed(title="🎙️ Voice Time Leaderboard", color=discord.Color.gold(),
                              description="\n".join(lines) or "No one has banked voice time yet — opt in with /voicexp optin!")
        if me not in [r["user_id"] for r in top]:
            all_rows = await list_voice_xp_users(gid)
            ordered = sorted(all_rows, key=lambda r: int(r.get("total_minutes", 0)), reverse=True)
            rank = next((i for i, r in enumerate(ordered, 1) if r["user_id"] == me), 0)
            if rank:
                row = next(r for r in ordered if r["user_id"] == me)
                embed.set_footer(text=f"You are #{rank} with {_fmt_minutes(row.get('total_minutes', 0))} "
                                      f"· {int(row.get('total_voice_xp', 0)):,} voice XP")
        await ctx.respond(embed=embed)

    # ---------- admin commands ----------

    @voicexp.command(name="config", description="Show the server's voice XP settings (admins).")
    @extra_help("Shows enabled state, XP rate, daily cap, and how many members are opted in.")
    @admin_required()
    async def voicexp_config(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        gid = str(ctx.guild.id)
        cfg = await get_voice_xp_config(gid)
        rows = await list_voice_xp_users(gid)
        opted_in = sum(1 for r in rows if r.get("opted_in"))
        embed = discord.Embed(title="🎙️ Voice XP Settings", color=discord.Color.blue())
        embed.add_field(name="Enabled", value="Yes" if cfg.get("enabled", True) else "No", inline=True)
        embed.add_field(name="Rate", value=f"{cfg.get('xp_per_minute', VOICE_XP_DEFAULT_RATE)} XP/minute", inline=True)
        embed.add_field(name="Daily cap", value=_cap_text(cfg.get("daily_cap_xp", VOICE_XP_DEFAULT_DAILY_CAP)), inline=True)
        embed.add_field(name="Opted in", value=f"{opted_in} member{'s' if opted_in != 1 else ''}", inline=True)
        embed.add_field(name="Guards", value="Needs 1+ other non-bot person · muted/deafened/AFK time never counts · stage channels excluded", inline=False)
        await ctx.respond(embed=embed, ephemeral=True)

    @voicexp.command(name="setrate", description="Set XP earned per minute of voice time (admins).")
    @extra_help("1-10 XP per qualifying minute. Default 1.")
    @admin_required()
    async def voicexp_setrate(self, ctx, rate: int):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        if rate < 1 or rate > 10:
            return await ctx.respond("Rate must be between 1 and 10 XP per minute.", ephemeral=True)
        gid = str(ctx.guild.id)
        await save_voice_xp_config(gid, {"xp_per_minute": rate})
        await ctx.respond(f"Voice XP rate set to **{rate} XP/minute**.", ephemeral=True)

    @voicexp.command(name="setcap", description="Set the daily voice XP cap per user, 0 for no cap (admins).")
    @extra_help("0 means unlimited. Default 100 XP per UTC day.")
    @admin_required()
    async def voicexp_setcap(self, ctx, cap: int):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        if cap < 0 or cap > 1000:
            return await ctx.respond("Cap must be between 0 (no cap) and 1000 XP/day.", ephemeral=True)
        gid = str(ctx.guild.id)
        await save_voice_xp_config(gid, {"daily_cap_xp": cap})
        await ctx.respond(f"Daily voice XP cap set to **{_cap_text(cap)}**.", ephemeral=True)

    @voicexp.command(name="enable", description="Enable voice XP for this server (admins).")
    @admin_required()
    async def voicexp_enable(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        await save_voice_xp_config(str(ctx.guild.id), {"enabled": True})
        await ctx.respond("Voice XP is now **enabled** for this server.", ephemeral=True)

    @voicexp.command(name="disable", description="Disable voice XP for this server (admins).")
    @extra_help("Stops all accrual immediately; banked totals and opt-ins are kept.")
    @admin_required()
    async def voicexp_disable(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Voice XP commands only work in a server.", ephemeral=True)
        await save_voice_xp_config(str(ctx.guild.id), {"enabled": False})
        await ctx.respond("Voice XP is now **disabled** for this server. Banked totals and opt-ins are kept.",
                          ephemeral=True)


def setup(bot):
    bot.add_cog(VoiceXP(bot))
