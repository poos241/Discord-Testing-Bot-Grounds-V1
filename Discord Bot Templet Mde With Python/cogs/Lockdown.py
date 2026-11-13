import time
import traceback

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
# Default server-wide lock when /lockdown lockall is given no duration:
# a timed lock that heals itself, so one tap can never silence the
# whole server forever. A single-channel /lockdown lock can still be
# permanent; the server-wide switch cannot.
LOCKALL_DEFAULT_MINUTES = 60
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


class LockallConfirmView(discord.ui.View):
    """Confirm a server-wide lockdown before any channel is touched.

    The command only builds the list of channels; the Confirm button
    re-checks the lockall gate at click time (so someone who lost the
    grant after the prompt opened cannot fire another mod's lock) and
    then runs the lock loop. A DB error on one channel is logged and
    reported, and the loop keeps going -- a bad save must not abort a
    server-wide lock half-way through and leave the interaction failed.
    """

    def __init__(self, cog, guild, moderator_id, reason, unlock_at,
                 to_lock, already_locked):
        super().__init__(timeout=180)
        self.cog = cog
        self.guild = guild
        self.moderator_id = moderator_id
        self.reason = reason
        self.unlock_at = unlock_at
        self.to_lock = list(to_lock)
        self.already_locked = list(already_locked)
        self.done = False

    @discord.ui.button(label="Yes, lock all channels",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, button: discord.ui.Button,
                      interaction: discord.Interaction):
        if self.done:
            await interaction.response.send_message(
                "This lockdown was already confirmed or cancelled.",
                ephemeral=True)
            return
        self.done = True
        from utils.permissions import (check_interaction_permission,
                                       _default_manage_or_admin)
        if not await check_interaction_permission(
                interaction, "lockdown_lockall", _default_manage_or_admin):
            return
        await interaction.response.defer(ephemeral=True)
        gid = str(self.guild.id)
        locked, skipped, failed = [], [], []
        for channel in self.to_lock:
            try:
                if await get_lockdown(gid, str(channel.id)):
                    skipped.append(channel.mention)
                    continue
                await self.cog._lock_channel(
                    self.guild, channel, self.moderator_id, self.reason,
                    self.unlock_at, "server")
                locked.append(channel.mention)
            except (discord.Forbidden, discord.HTTPException):
                failed.append(f"{channel.mention} (no permission)")
            except Exception as e:
                print(f"[Lockdown] lockall: failed to lock "
                      f"#{channel.name}: {e!r}")
                failed.append(f"{channel.mention} (save failed -- "
                              f"check the channel)")
        timer = f" Auto-unlocks <t:{self.unlock_at}:R>."
        lines = [f"Server lockdown: **{len(locked)}** channels locked.{timer}"]
        total_skipped = len(skipped) + len(self.already_locked)
        if total_skipped:
            lines.append(f"Already locked, left alone: {total_skipped}.")
        if failed:
            lines.append("Could not lock (%d): %s" % (
                len(failed),
                ", ".join(failed[:10]) + ("..." if len(failed) > 10 else "")))
        await interaction.followup.send("\n".join(lines), ephemeral=True)
        await self.cog._log(self.guild, discord.Embed(
            title="Server Locked Down",
            description=f"{len(locked)} channels locked by "
                        f"<@{self.moderator_id}>."
                        + f" Auto-unlock <t:{self.unlock_at}:R>."
                        + (f" Reason: {self.reason}" if self.reason else ""),
            color=discord.Color.red(),
            timestamp=discord.utils.utcnow()))
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button,
                     interaction: discord.Interaction):
        if self.done:
            await interaction.response.send_message(
                "This lockdown was already confirmed or cancelled.",
                ephemeral=True)
            return
        self.done = True
        await interaction.response.edit_message(
            content="Server lockdown cancelled -- nothing was locked.",
            view=None)
        self.stop()


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
        """Save the lock record first, then deny @everyone send_messages.

        The record is the source of truth for /lockdown status and the
        auto-unlock ticker, so it must exist (and be verified readable)
        before Discord is touched. The old order -- edit first, save
        second -- left a channel locked with no record when the save
        failed: invisible to status, never auto-unlocked. If the save
        fails here, the channel is untouched and the DB error
        propagates to the caller. If the Discord edit then fails with
        Forbidden/HTTPException, the edit definitely did not apply, so
        the record is rolled back; if the rollback itself fails, the
        stale row is logged loudly (it stays visible in status and
        self-heals at the auto-unlock tick). Any other edit error is
        re-raised with the record kept -- the edit may have applied,
        and a stale visible record is safer than an invisible lock.

        Returns the previous send_messages value (True/False/None).
        """
        everyone = guild.default_role
        previous = channel.overwrites_for(everyone).send_messages
        await save_lockdown(str(guild.id), str(channel.id), {
            "previous_send_messages": _prev_to_int(previous),
            "locked_by": str(moderator_id),
            "locked_at": int(time.time()),
            "unlock_at": unlock_at,
            "reason": reason or "",
            "scope": scope,
        })
        saved = await get_lockdown(str(guild.id), str(channel.id))
        if not saved:
            raise RuntimeError(
                f"lock record for #{channel.name} did not persist")
        try:
            await channel.set_permissions(
                everyone, send_messages=False,
                reason=reason or f"Channel locked by {moderator_id}")
        except (discord.Forbidden, discord.HTTPException):
            try:
                await delete_lockdown(str(guild.id), str(channel.id))
            except Exception as e:
                print(f"[Lockdown] _lock_channel: Discord edit failed "
                      f"for #{channel.name} AND the lock-record rollback "
                      f"failed: {e!r} -- stale row remains, visible in "
                      f"/lockdown status and cleared by the auto-unlock "
                      f"tick")
            raise
        except Exception:
            print(f"[Lockdown] _lock_channel: unexpected error locking "
                  f"#{channel.name} -- lock record KEPT (the edit may "
                  f"have applied; a visible record beats an invisible "
                  f"lock)")
            raise
        return previous

    async def _unlock_channel(self, guild, row, reason):
        """Restore the recorded @everyone overwrite and drop the row.

        Returns (ok, note). When the Discord edit fails, the row is
        KEPT on purpose: the channel is still locked, so the record
        must stay visible in /lockdown status and be retried -- the
        auto-unlock ticker picks a still-due timed lock up again on
        its next tick, and a permanent lock can be retried with
        /lockdown unlock once the bot can edit the channel again.
        The old behavior deleted the row on failure, which left a
        locked channel with no record and no retry -- only recoverable
        via the manual-unlock fallback, which resets the overwrite to
        unset instead of restoring the recorded previous value. A row
        is only dropped when the channel itself is gone (nothing left
        to unlock).
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
            print(f"[Lockdown] _unlock_channel: could not edit "
                  f"permissions for #{channel.name} in {guild.name} "
                  f"({e.__class__.__name__}) -- lock record KEPT, the "
                  f"channel is still locked; a timed lock is retried by "
                  f"the auto-unlock ticker, a permanent lock by "
                  f"/lockdown unlock once the bot can edit the channel")
            return False, (f"could not edit permissions "
                           f"({e.__class__.__name__}) -- the lock record "
                           f"was kept, so the channel is still locked")
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
        embed.set_footer(text="Powered by Havenly Bot")
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
            try:
                guild = self.bot.get_guild(int(row["guild_id"]))
                if guild is None:
                    # Bot left the server: drop the row, nothing to unlock.
                    await delete_lockdown(row["guild_id"], row["channel_id"])
                    continue
                channel = guild.get_channel(int(row["channel_id"]))
                ok, note = await self._unlock_channel(
                    guild, row, "Timed lockdown expired (automatic)")
                if channel is None:
                    # Channel is gone: _unlock_channel already cleared
                    # the stale row, nothing to log.
                    continue
                if ok:
                    print(f"[Lockdown] Auto-unlocked #{channel.name} in "
                          f"{guild.name} (ok={ok}, {note})")
                    await self._log(guild, discord.Embed(
                        title="Lockdown Expired",
                        description=f"{channel.mention} has been unlocked "
                                    f"(timed lockdown expired).",
                        color=discord.Color.green(),
                        timestamp=discord.utils.utcnow()))
                else:
                    # The channel is STILL locked: _unlock_channel kept
                    # the row on purpose, so the ticker retries it next
                    # minute. Say so loudly instead of logging a
                    # success that never happened.
                    print(f"[Lockdown] Auto-unlock FAILED for "
                          f"#{channel.name} in {guild.name}: {note} -- "
                          f"the channel is still locked; the lock record "
                          f"was kept and will be retried on the next tick")
                    await self._log(guild, discord.Embed(
                        title="Lockdown Auto-Unlock Failed",
                        description=f"{channel.mention} could NOT be "
                                    f"unlocked when its timed lockdown "
                                    f"expired: {note}. The channel is "
                                    f"still locked; the lock record was "
                                    f"kept and will be retried on the "
                                    f"next auto-unlock tick.",
                        color=discord.Color.red(),
                        timestamp=discord.utils.utcnow()))
            except Exception:
                # One bad row (DB error, malformed row, Discord error)
                # must never kill the sweep: log it loudly and move on.
                # The row stays queued and is retried on the next tick,
                # so a transient failure delays the unlock instead of
                # leaving it stuck until restart.
                print(f"[Lockdown] Auto-unlock failed for row {row!r}:")
                traceback.print_exc()
                continue

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
    async def lockdown_lock(self, ctx, channel: discord.TextChannel = None,
                            duration: int = None, reason: str = None):
        from utils.permissions import check_slash_permission, _default_manage_channels_or_admin
        if not await check_slash_permission(ctx, "lockdown_lock", _default_manage_channels_or_admin):
            return
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
        except Exception as e:
            # A save failure (record write or verify) means the channel
            # was left exactly as it was -- never report it as locked.
            print(f"[Lockdown] lockdown_lock: could not save lock record "
                  f"for #{target.name}: {e!r}")
            return await ctx.respond(
                f"Could not lock {target.mention}: the lock record could "
                f"not be saved, so the channel's lock state was not "
                f"changed. Try again.", ephemeral=True)
        timer = (f" Auto-unlocks <t:{unlock_at}:R>."
                 if unlock_at else " No auto-unlock set.")
        await ctx.respond(
            f"Locked {target.mention} ({action}).{timer}", ephemeral=True)
        await self._log(ctx.guild, self._lock_embed(
            "Channel Locked" if not existing else "Lockdown Timer Updated",
            target, ctx.user, reason, unlock_at))

    @lockdown.command(name="unlock", description="Unlock a channel, restoring its previous @everyone permission.")
    @extra_help("Unlocks one channel (default: the channel you run it in). Restores whatever @everyone send_messages was before the lock. Also clears a manual lock (one set by hand in channel settings) by resetting the overwrite to unset.")
    async def lockdown_unlock(self, ctx, channel: discord.TextChannel = None):
        from utils.permissions import check_slash_permission, _default_manage_channels_or_admin
        if not await check_slash_permission(ctx, "lockdown_unlock", _default_manage_channels_or_admin):
            return
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
    @extra_help("Server-wide raid/spam switch: denies @everyone send_messages in every text channel. Needs Manage Server or Administrator, and always asks for confirmation first -- one tap can no longer silence the whole server. Channels already locked by the bot are left alone (their timers are not touched). A duration in minutes sets a timed lock that auto-unlocks channel by channel; with no duration the lock defaults to 60 minutes, so a server-wide lock can never be permanent by accident (use /lockdown lock for a permanent single-channel lock). Forum channels are not locked -- lock those individually if needed.")
    async def lockdown_lockall(self, ctx, duration: int = None,
                               reason: str = None):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "lockdown_lockall", _default_manage_or_admin):
            return
        if ctx.guild is None:
            return await ctx.respond("Lockdown commands only work in a server.",
                                     ephemeral=True)
        defaulted = duration is None
        if defaulted:
            duration = LOCKALL_DEFAULT_MINUTES
        if duration < 1 or duration > LOCKDOWN_MAX_MINUTES:
            return await ctx.respond(
                f"Duration must be between 1 and {LOCKDOWN_MAX_MINUTES} minutes "
                f"(1 week).", ephemeral=True)
        unlock_at = int(time.time()) + duration * 60
        gid = str(ctx.guild.id)
        to_lock, already_locked = [], []
        for channel in ctx.guild.text_channels:
            try:
                locked = await get_lockdown(gid, str(channel.id))
            except Exception as e:
                # A read failure must not abort the prompt: treat the
                # channel as unlocked here; the confirm loop re-checks
                # and reports the failure per channel if it persists.
                print(f"[Lockdown] lockall: could not read lock state "
                      f"for #{channel.name}: {e!r}")
                locked = None
            if locked:
                already_locked.append(channel)
            else:
                to_lock.append(channel)
        if not to_lock:
            return await ctx.respond(
                "Every text channel is already locked by the bot -- "
                "nothing to do.", ephemeral=True)
        text = (f"Lock **{len(to_lock)}** text channel(s) for "
                f"**{_fmt_minutes(duration)}**"
                f"{' (default -- no duration given)' if defaulted else ''}? "
                f"Auto-unlock <t:{unlock_at}:R>.")
        if already_locked:
            text += (f" {len(already_locked)} channel(s) already locked, "
                     f"left alone.")
        if reason:
            text += f" Reason: {reason}"
        await ctx.respond(
            text,
            view=LockallConfirmView(self, ctx.guild, ctx.user.id, reason,
                                    unlock_at, to_lock, already_locked),
            ephemeral=True)

    @lockdown.command(name="unlockall", description="Unlock every channel the bot has locked in this server.")
    @extra_help("Reverses /lockdown lockall and any individual bot locks in one go, restoring each channel's previous @everyone permission. Channels locked by hand are not touched -- unlock those with /lockdown unlock.")
    async def lockdown_unlockall(self, ctx):
        from utils.permissions import check_slash_permission, _default_manage_channels_or_admin
        if not await check_slash_permission(ctx, "lockdown_unlockall", _default_manage_channels_or_admin):
            return
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
    async def lockdown_slowmode(self, ctx, seconds: int,
                                channel: discord.TextChannel = None,
                                reason: str = None):
        from utils.permissions import check_slash_permission, _default_manage_channels_or_admin
        if not await check_slash_permission(ctx, "lockdown_slowmode", _default_manage_channels_or_admin):
            return
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
    async def lockdown_status(self, ctx):
        from utils.permissions import check_slash_permission, _default_manage_channels_or_admin
        if not await check_slash_permission(ctx, "lockdown_status", _default_manage_channels_or_admin):
            return
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
