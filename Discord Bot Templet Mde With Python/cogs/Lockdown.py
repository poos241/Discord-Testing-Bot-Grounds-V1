import time

import discord
from discord.ext import commands, tasks
from discord.commands import SlashCommandGroup

from config import GUILD_IDS, Manage_channels_required, extra_help
from data.DB.db import database
from data.DB.Storage.storage import (
    get_lockdown,
    save_lockdown,
    delete_lockdown,
    list_lockdowns,
    list_due_lockdowns,
)

# Longest timed lockdown: 1 week (Discord-side there is no cap on how
# long a channel can stay locked; the cap here just keeps a typo like
# 99999 minutes from locking a channel effectively forever).
LOCKDOWN_MAX_MINUTES = 10080
# Discord slowmode cap: 6 hours.
SLOWMODE_MAX_SECONDS = 21600


def _prev_to_int(value):
    """@everyone send_messages overwrite -> storable int (None -> -1)."""
    if value is None:
        return -1
    return 1 if value else 0


def _int_to_prev(value):
    """Stored int -> overwrite value (None restores the unset state)."""
    if value is None or int(value) == -1:
        return None
    return bool(int(value))


def _fmt_minutes(minutes):
    """90 -> '1h 30m', 45 -> '45m', 10080 -> '7d'."""
    minutes = int(minutes)
    if minutes >= 1440 and minutes % 1440 == 0:
        days = minutes // 1440
        return f"{days}d"
    if minutes >= 60:
        hours, mins = divmod(minutes, 60)
        return f"{hours}h {mins}m" if mins else f"{hours}h"
    return f"{minutes}m"


class Lockdown(commands.Cog):
    """Channel/server lockdown, slowmode, and timed auto-unlock.

    Locking denies @everyone send_messages on a channel and records
    what the overwrite was before, so unlocking restores exactly that
    state instead of blindly re-allowing. Timed locks live in the
    lockdown_channels table, so the auto-unlock ticker picks them up
    again after a bot restart.
    """

    lockdown = SlashCommandGroup("lockdown", "Lockdown and slowmode controls",
                                 guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        self.auto_unlock.start()

    # ---------- internals ----------

    async def _lock_channel(self, guild, channel, moderator_id, reason,
                            unlock_at, scope):
        """Deny @everyone send_messages; record the previous value.

        Returns the previous send_messages value (True/False/None).
        """
        everyone = guild.default_role
        previous = channel.overwrites_for(everyone).send_messages
        await channel.set_permissions(
            everyone, send_messages=False,
            reason=reason or f"Channel locked by {moderator_id}")
        await save_lockdown(str(guild.id), str(channel.id), {
            "previous_send_messages": _prev_to_int(previous),
            "locked_by": str(moderator_id),
            "locked_at": int(time.time()),
            "unlock_at": unlock_at,
            "reason": reason or "",
            "scope": scope,
        })
        return previous

    async def _unlock_channel(self, guild, row, reason):
        """Restore the recorded @everyone overwrite and drop the row.

        Returns (ok, note): ok is False when the channel is gone or
        the bot could not edit it; the row is still dropped so a
        dead lock never blocks the status list.
        """
        gid, cid = row["guild_id"], row["channel_id"]
        channel = guild.get_channel(int(cid))
        if channel is None:
            await delete_lockdown(gid, cid)
            return False, "channel no longer exists (stale lock cleared)"
        try:
            await channel.set_permissions(
                guild.default_role,
                send_messages=_int_to_prev(row.get("previous_send_messages")),
                reason=reason)
        except (discord.Forbidden, discord.HTTPException) as e:
            await delete_lockdown(gid, cid)
            return False, f"could not edit permissions ({e.__class__.__name__})"
        await delete_lockdown(gid, cid)
        return True, "unlocked"

    async def _log(self, guild, embed):
        """Best-effort post to the Logger's moderation channel."""
        try:
            logger_cog = self.bot.get_cog("ModerationLogger")
            if logger_cog is not None:
                await logger_cog.send(guild, "moderation", embed)
        except Exception:
            pass

    def _lock_embed(self, title, channel, moderator, reason, unlock_at):
        embed = discord.Embed(
            title=title, color=discord.Color.red(),
            timestamp=discord.utils.utcnow())
        embed.add_field(name="Channel", value=channel.mention, inline=True)
        embed.add_field(name="Moderator", value=str(moderator), inline=True)
        if reason:
            embed.add_field(name="Reason", value=reason, inline=False)
        if unlock_at:
            embed.add_field(name="Auto-unlock",
                            value=f"<t:{unlock_at}:R>", inline=True)
        embed.set_footer(text="Kush Bush Logger")
        return embed

    def _resolve_channel(self, ctx, channel):
        """Channel option, or the channel the command ran in.

        Threads inherit their parent's overwrites, so they cannot be
        locked directly -- the mod must pick a real text channel.
        """
        target = channel or ctx.channel
        if isinstance(target, discord.TextChannel):
            return target
        return None

    # ---------- auto-unlock ticker ----------

    @tasks.loop(minutes=1)
    async def auto_unlock(self):
        now = int(time.time())
        try:
            due = await list_due_lockdowns(now)
        except Exception as e:
            print(f"[Lockdown] Auto-unlock sweep failed: {e!r}")
            return
        for row in due:
            guild = self.bot.get_guild(int(row["guild_id"]))
            if guild is None:
                # Bot left the server: drop the row, nothing to unlock.
                await delete_lockdown(row["guild_id"], row["channel_id"])
                continue
            channel = guild.get_channel(int(row["channel_id"]))
            ok, note = await self._unlock_channel(
                guild, row, "Timed lockdown expired (automatic)")
            if channel is not None:
                print(f"[Lockdown] Auto-unlocked #{channel.name} in "
                      f"{guild.name} (ok={ok}, {note})")
                await self._log(guild, discord.Embed(
                    title="Lockdown Expired",
                    description=f"{channel.mention} has been unlocked "
                                f"(timed lockdown expired).",
                    color=discord.Color.green(),
                    timestamp=discord.utils.utcnow()))

    @auto_unlock.before_loop
    async def before_auto_unlock(self):
        await self.bot.wait_until_ready()
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[Lockdown] DB connect check failed: {e!r}")

    # ---------- commands ----------

    @lockdown.command(name="lock", description="Lock a channel so @everyone cannot send messages.")
    @extra_help("Locks one channel (default: the channel you run it in). A duration in minutes sets a timed lock that auto-unlocks on its own, even across a bot restart. Unlocking restores the channel's previous @everyone permission, it does not just re-allow sending.")
    @Manage_channels_required()
    async def lockdown_lock(self, ctx, channel: discord.TextChannel = None,
                            duration: int = None, reason: str = None):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        target = self._resolve_channel(ctx, channel)
        if target is None:
            return await ctx.respond(
                "Pick a text channel to lock (threads cannot be locked "
                "directly -- lock their parent channel instead).",
                ephemeral=True)
        if duration is not None and (duration < 1 or duration > LOCKDOWN_MAX_MINUTES):
            return await ctx.respond(
                f"Duration must be between 1 and {LOCKDOWN_MAX_MINUTES} minutes "
                f"(1 week).", ephemeral=True)
        gid = str(ctx.guild.id)
        existing = await get_lockdown(gid, str(target.id))
        unlock_at = (int(time.time()) + duration * 60) if duration else None
        try:
            if existing:
                # Already locked by the bot: keep the recorded previous
                # value, just refresh the timer/reason.
                existing["unlock_at"] = unlock_at
                existing["reason"] = reason or existing.get("reason", "")
                existing["locked_by"] = str(ctx.user.id)
                await save_lockdown(gid, str(target.id), existing)
                action = "already locked -- timer updated"
            else:
                await self._lock_channel(ctx.guild, target, ctx.user.id,
                                         reason, unlock_at, "channel")
                action = "locked"
        except (discord.Forbidden, discord.HTTPException):
            return await ctx.respond(
                f"Could not lock {target.mention}: I do not have permission "
                f"to edit that channel's overwrites.", ephemeral=True)
        timer = (f" Auto-unlocks <t:{unlock_at}:R>."
                 if unlock_at else " No auto-unlock set.")
        await ctx.respond(
            f"Locked {target.mention} ({action}).{timer}", ephemeral=True)
        await self._log(ctx.guild, self._lock_embed(
            "Channel Locked" if not existing else "Lockdown Timer Updated",
            target, ctx.user, reason, unlock_at))

    @lockdown.command(name="unlock", description="Unlock a channel, restoring its previous @everyone permission.")
    @extra_help("Unlocks one channel (default: the channel you run it in). Restores whatever @everyone send_messages was before the lock. Also clears a manual lock (one set by hand in channel settings) by resetting the overwrite to unset.")
    @Manage_channels_required()
    async def lockdown_unlock(self, ctx, channel: discord.TextChannel = None):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        target = self._resolve_channel(ctx, channel)
        if target is None:
            return await ctx.respond(
                "Pick a text channel to unlock.", ephemeral=True)
        gid = str(ctx.guild.id)
        row = await get_lockdown(gid, str(target.id))
        if row:
            ok, note = await self._unlock_channel(
                ctx.guild, row, f"Unlocked by {ctx.user}")
            if not ok:
                return await ctx.respond(
                    f"Could not unlock {target.mention}: {note}.",
                    ephemeral=True)
            await ctx.respond(f"Unlocked {target.mention}.", ephemeral=True)
            await self._log(ctx.guild, discord.Embed(
                title="Channel Unlocked",
                description=f"{target.mention} unlocked by {ctx.user}.",
                color=discord.Color.green(),
                timestamp=discord.utils.utcnow()))
            return
        # No bot record: a hand-set lock still deserves an unlock path.
        current = target.overwrites_for(ctx.guild.default_role).send_messages
        if current is False:
            try:
                await target.set_permissions(
                    ctx.guild.default_role, send_messages=None,
                    reason=f"Manual lock cleared by {ctx.user}")
            except (discord.Forbidden, discord.HTTPException):
                return await ctx.respond(
                    f"Could not unlock {target.mention}: I do not have "
                    f"permission to edit that channel's overwrites.",
                    ephemeral=True)
            await ctx.respond(
                f"Unlocked {target.mention} (it was locked by hand, not by "
                f"the bot, so the overwrite was reset to unset).",
                ephemeral=True)
            return
        await ctx.respond(f"{target.mention} is not locked.", ephemeral=True)

    @lockdown.command(name="lockall", description="Lock every text channel in the server.")
    @extra_help("Server-wide raid/spam switch: denies @everyone send_messages in every text channel. Channels already locked by the bot are left alone (their timers are not touched). A duration sets a timed server lock that auto-unlocks channel by channel. Forum channels are not locked -- lock those individually if needed.")
    @Manage_channels_required()
    async def lockdown_lockall(self, ctx, duration: int = None,
                               reason: str = None):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        if duration is not None and (duration < 1 or duration > LOCKDOWN_MAX_MINUTES):
            return await ctx.respond(
                f"Duration must be between 1 and {LOCKDOWN_MAX_MINUTES} minutes "
                f"(1 week).", ephemeral=True)
        await ctx.defer(ephemeral=True)
        unlock_at = (int(time.time()) + duration * 60) if duration else None
        gid = str(ctx.guild.id)
        locked, skipped, failed = [], [], []
        for channel in ctx.guild.text_channels:
            if await get_lockdown(gid, str(channel.id)):
                skipped.append(channel.mention)
                continue
            try:
                await self._lock_channel(ctx.guild, channel, ctx.user.id,
                                         reason, unlock_at, "server")
                locked.append(channel.mention)
            except (discord.Forbidden, discord.HTTPException):
                failed.append(channel.mention)
        timer = (f" Auto-unlocks <t:{unlock_at}:R>."
                 if unlock_at else " No auto-unlock set.")
        lines = [f"Server lockdown: **{len(locked)}** channels locked.{timer}"]
        if skipped:
            lines.append(f"Already locked, left alone: {len(skipped)}.")
        if failed:
            lines.append(f"Could not lock ({len(failed)}): "
                         + ", ".join(failed[:10])
                         + ("..." if len(failed) > 10 else ""))
        await ctx.followup.send("\n".join(lines), ephemeral=True)
        await self._log(ctx.guild, discord.Embed(
            title="Server Locked Down",
            description=f"{len(locked)} channels locked by {ctx.user}."
                        + (f" Auto-unlock <t:{unlock_at}:R>." if unlock_at else "")
                        + (f" Reason: {reason}" if reason else ""),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()))

    @lockdown.command(name="unlockall", description="Unlock every channel the bot has locked in this server.")
    @extra_help("Reverses /lockdown lockall and any individual bot locks in one go, restoring each channel's previous @everyone permission. Channels locked by hand are not touched -- unlock those with /lockdown unlock.")
    @Manage_channels_required()
    async def lockdown_unlockall(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        await ctx.defer(ephemeral=True)
        rows = await list_lockdowns(str(ctx.guild.id))
        unlocked, failed = [], []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            ok, note = await self._unlock_channel(
                ctx.guild, row, f"Unlocked by {ctx.user}")
            if ok and channel is not None:
                unlocked.append(channel.mention)
            elif channel is not None:
                failed.append(f"{channel.mention} ({note})")
        msg = f"Unlocked **{len(unlocked)}** channels."
        if failed:
            msg += "\nCould not unlock: " + ", ".join(failed[:10])
        await ctx.followup.send(msg, ephemeral=True)
        await self._log(ctx.guild, discord.Embed(
            title="Server Unlocked",
            description=f"{len(unlocked)} channels unlocked by {ctx.user}.",
            color=discord.Color.green(),
            timestamp=discord.utils.utcnow()))

    @lockdown.command(name="slowmode", description="Set slowmode on a channel (0 turns it off).")
    @extra_help("Seconds between messages per user, 0-21600 (6 hours). Default channel is the one you run it in. Slowmode does not stop mods or anyone with Manage Messages from chatting, it only slows regular members.")
    @Manage_channels_required()
    async def lockdown_slowmode(self, ctx, seconds: int,
                                channel: discord.TextChannel = None,
                                reason: str = None):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        if seconds < 0 or seconds > SLOWMODE_MAX_SECONDS:
            return await ctx.respond(
                f"Slowmode must be between 0 and {SLOWMODE_MAX_SECONDS} "
                f"seconds (6 hours).", ephemeral=True)
        target = self._resolve_channel(ctx, channel)
        if target is None:
            return await ctx.respond(
                "Pick a text channel to set slowmode on.", ephemeral=True)
        try:
            await target.edit(slowmode_delay=seconds,
                              reason=reason or f"Slowmode set by {ctx.user}")
        except (discord.Forbidden, discord.HTTPException):
            return await ctx.respond(
                f"Could not set slowmode on {target.mention}: I do not have "
                f"permission to edit that channel.", ephemeral=True)
        if seconds == 0:
            await ctx.respond(f"Slowmode turned off in {target.mention}.",
                              ephemeral=True)
        else:
            await ctx.respond(
                f"Slowmode set to **{seconds}s** in {target.mention}.",
                ephemeral=True)

    @lockdown.command(name="status", description="Show every channel the bot currently has locked, and pending auto-unlocks.")
    @extra_help("Lists bot-locked channels with who locked them, the reason, and when a timed lock auto-unlocks. Channels locked by hand do not appear here -- only locks the bot is tracking.")
    @Manage_channels_required()
    async def lockdown_status(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        rows = await list_lockdowns(str(ctx.guild.id))
        if not rows:
            return await ctx.respond(
                "No channels are currently locked by the bot.",
                ephemeral=True)
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            name = channel.mention if channel else f"(deleted channel `{row['channel_id']}`)"
            unlock = (f"auto-unlocks <t:{row['unlock_at']}:R>"
                      if row.get("unlock_at") else "no auto-unlock")
            scope = "server lockdown" if row.get("scope") == "server" else "channel lock"
            reason = f" — {row['reason']}" if row.get("reason") else ""
            lines.append(f"{name} ({scope}, <@{row['locked_by']}>): "
                         f"{unlock}{reason}")
        embed = discord.Embed(
            title="Locked Channels", color=discord.Color.orange(),
            description="\n".join(lines[:25]))
        if len(lines) > 25:
            embed.set_footer(text=f"And {len(lines) - 25} more locked channels.")
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Lockdown(bot))
