# cogs/VoiceXP.py
"""Voice time XP, merged into the level system (rebuilt 2026-11-14).

Automatic XP for time in voice channels — no opt-in, no opt-out, no
daily cap. Voice XP flows straight into the main level XP via
award_xp_batch from cogs/Level_system.py, so it is just part of the
level system now. There are no /voicexp commands anymore.

How it accrues (1-minute ticker):
  - With at least one OTHER non-bot person in the channel: each member
    earns 1-10 random XP per minute.
  - Alone (only you, or only you + bots): each member earns 1-10 random
    XP every 5 minutes (solo minutes accumulate in memory; the award
    lands on the 5th consecutive solo minute).
  - Bots never count as a "person" for the someone-else check, but a
    bot being present does not stop you earning when real people are
    there.
  - No XP in the server AFK channel, and no XP in channels on the
    no-voice-XP ("sleep") list (settings["no_voice_xp_channels"] in the
    levels blob, set via /no_xp_bulk).
  - Muted/deafened members still earn (no exclusion).
  - Stage channels do not count (only guild.voice_channels are scanned).
  - Voice XP only accrues while the level system is enabled for the
    server (/toggle_levels, off by default). When levels are off, no
    minutes are banked at all.
  - Pending solo minutes live only in memory and are lost on a bot
    restart. Banked totals live in the voice_xp_users table.

Tables: voice_xp_users in data/DB/models.py (total_minutes and
total_voice_xp ledger). The voice_xp_config table is no longer used
(no rate, no cap, no per-server toggle); the sleep list lives in the
levels settings JSON.
"""
import asyncio
import random
import time

from discord.ext import commands, tasks

from data.DB.db import database
from data.DB.Storage.storage import (
    get_levels,
    get_voice_xp_user,
    save_voice_xp_user,
    list_voice_xp_users,
)
from cogs.Level_system import award_xp_batch, levels_enabled

# Voice XP earn rates.
VOICE_XP_SOLO_CHUNK = 5  # solo minutes per random XP award


class VoiceXP(commands.Cog):
    """Voice time XP (automatic, part of the level system)."""

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> consecutive solo minutes (< SOLO_CHUNK).
        # Reset when the member is in a social minute or leaves voice.
        self._pending = {}
        # (guild_id, user_id) -> asyncio.Lock serializing that member's
        # tick and flush paths (P3-13). Kept for the cog's lifetime.
        self._locks = {}
        self.voice_tick.start()

    def _lock_for(self, gid, uid):
        """Return the (lazily created) asyncio.Lock for one member's
        voice XP. Dict get/set here is a single synchronous step with
        no await in between, so two coroutines can't create two
        different locks for the same member on the event loop."""
        key = (gid, uid)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    # ---------- internals ----------

    async def _tick_guild(self, guild):
        if not await levels_enabled(guild.id):
            return  # P1-20: level system off — no accrual at all.
        gid = str(guild.id)
        db = await get_levels(gid)
        sleep = set(str(c) for c in
                    db.get("settings", {}).get("no_voice_xp_channels", [])
                    or [])
        afk_id = guild.afk_channel.id if guild.afk_channel else None
        # (member, is_social) for every member earning a minute.
        qualifying = []
        for channel in guild.voice_channels:
            if channel.id == afk_id:
                continue  # sitting in AFK never counts
            if str(channel.id) in sleep:
                continue  # sleep channel: no voice XP
            humans = [m for m in channel.members if not m.bot]
            if not humans:
                continue
            social = len(humans) >= 2
            for member in humans:
                vs = member.voice
                if vs is None or vs.channel is None or vs.channel.id != channel.id:
                    continue
                qualifying.append((member, social))
        if not qualifying:
            return
        # P3-13: hold every qualifying member's lock from BEFORE the
        # voice rows are loaded until the bank + save is done, so a
        # flush landing mid-tick can't double-bank the same minutes.
        # Locks are taken in user-id order so two ticks can never
        # deadlock each other, and released in the finally even when
        # the batch raises.
        held = []
        try:
            for member, _ in sorted(qualifying, key=lambda kv: str(kv[0].id)):
                lock = self._lock_for(gid, str(member.id))
                await lock.acquire()
                held.append(lock)
            rows = {r["user_id"]: r for r in await list_voice_xp_users(gid)}
            awards = []  # (user_id, display_name, xp) for this tick
            prepared = []  # (member, row) whose ledger changed
            for member, social in qualifying:
                uid = str(member.id)
                row = rows.get(uid)
                if row is None:
                    row = {}
                row["total_minutes"] = int(row.get("total_minutes", 0)) + 1
                row["display_name"] = member.display_name
                xp = 0
                if social:
                    # With someone else here: 1-10 XP every minute.
                    # A solo streak is broken by a social minute.
                    self._pending.pop((gid, uid), None)
                    xp = random.randint(1, 1)
                else:
                    # Alone: 1-10 XP every 5th consecutive solo minute.
                    pending = self._pending.get((gid, uid), 0) + 1
                    if pending >= VOICE_XP_SOLO_CHUNK:
                        xp = random.randint(1, 1)
                        self._pending.pop((gid, uid), None)
                    else:
                        self._pending[(gid, uid)] = pending
                if xp > 0:
                    row["total_voice_xp"] = int(row.get("total_voice_xp", 0)) + xp
                    awards.append((member.id, member.display_name, xp))
                prepared.append((member, row))
            if awards:
                await award_xp_batch(guild, awards, fallback_channel=None)
            for member, row in prepared:
                try:
                    await save_voice_xp_user(gid, str(member.id), row)
                except Exception as e:
                    print(f"[VoiceXP] Voice row save failed for {member.id}: {e!r}")
        finally:
            for lock in held:
                lock.release()

    async def _flush_pending(self, guild, member):
        """Drop a member's unbanked solo minutes (e.g. they left voice).

        Solo XP only pays out on the 5th consecutive solo minute, so
        minutes under that are simply discarded on leave. Social XP
        is awarded every minute by the tick, so there is nothing to
        flush for it."""
        self._pending.pop((str(guild.id), str(member.id)), None)

    # ---------- scheduler ----------

    @tasks.loop(minutes=1)
    async def voice_tick(self):
        started = time.monotonic()
        for guild in self.bot.guilds:
            try:
                await self._tick_guild(guild)
            except Exception as e:
                print(f"[VoiceXP] Tick failed for guild {guild.id}: {e!r}")
        elapsed = time.monotonic() - started
        if elapsed > 10:
            print(f"[VoiceXP] Tick took {elapsed:.1f}s for "
                  f"{len(self.bot.guilds)} guild(s) — tick may drift")

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
        # drop unbanked solo minutes.
        try:
            await self._flush_pending(member.guild, member)
        except Exception as e:
            print(f"[VoiceXP] Flush failed for {member.id}: {e!r}")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Gone from the server: drop unbanked solo minutes, don't award.
        self._pending.pop((str(member.guild.id), str(member.id)), None)


def setup(bot):
    bot.add_cog(VoiceXP(bot))
