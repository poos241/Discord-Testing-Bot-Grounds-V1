# cogs/Backup.py
"""Unified backup + restore: daily scheduled snapshots plus a small
Discord-side interface. The heavy lifting lives in utils/backup.py;
this cog only schedules it and exposes /backup now + /backup status.

Scheduled snapshots run once a day at BACKUP_DAILY_HOUR (default 04:00)
PC local time, when the bot is running. Manual snapshots and restores
are also available from the web UI (/backups, moderator-only), which is
where restores live — a restore is a deliberate, confirm-first action
and belongs on the dashboard, not in a chat command.
"""

import datetime

import discord
from discord.ext import commands, tasks
from discord.commands import SlashCommandGroup

from config import GUILD_IDS
from utils.backup import (
    create_snapshot,
    list_snapshots,
    scheduled_hour,
)


def is_mod(ctx):
    """Manage Messages or Administrator, matching this bot's mod
    checks (see Tickets.is_mod)."""
    if ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


_BACKUP_TIME = datetime.time(hour=scheduled_hour(), minute=0)


class Backup(commands.Cog):
    """Daily data snapshots + /backup commands."""

    backup = SlashCommandGroup(
        "backup", "Bot data backups", guild_ids=GUILD_IDS
    )

    def __init__(self, bot):
        self.bot = bot
        self.daily_loop.start()

    # ---------- scheduler ----------

    @tasks.loop(time=_BACKUP_TIME)
    async def daily_loop(self):
        try:
            summary = create_snapshot("scheduled")
            print(
                "[Backup] Scheduled snapshot: %s (%d files)"
                % (summary["name"], len(summary["files"]))
            )
        except Exception as exc:
            print("[Backup] Scheduled snapshot failed: %r" % (exc,))

    @daily_loop.before_loop
    async def before_daily_loop(self):
        await self.bot.wait_until_ready()

    # ---------- member commands ----------

    @backup.command(
        name="now",
        description="Take a backup snapshot right now (mods only).",
    )
    async def backup_now(self, ctx):
        if not is_mod(ctx):
            await ctx.respond(
                "You need Manage Messages or Administrator to take a backup.",
                ephemeral=True,
            )
            return
        await ctx.defer(ephemeral=True)
        try:
            summary = create_snapshot("manual")
            names = ", ".join(f["name"] for f in summary["files"])
            await ctx.followup.send(
                "Snapshot saved: `%s`\n%d files (%s). "
                "View and restore snapshots from the web UI at /backups."
                % (summary["name"], len(summary["files"]), names),
                ephemeral=True,
            )
        except Exception as exc:
            print("[Backup] Manual snapshot failed: %r" % (exc,))
            await ctx.followup.send(
                "Snapshot failed: %r" % (exc,),
                ephemeral=True,
            )

    @backup.command(
        name="status",
        description="Show the latest backup snapshot (mods only).",
    )
    async def backup_status(self, ctx):
        if not is_mod(ctx):
            await ctx.respond(
                "You need Manage Messages or Administrator to check backups.",
                ephemeral=True,
            )
            return
        snapshots = list_snapshots()
        if not snapshots:
            await ctx.respond(
                "No snapshots yet. Scheduled snapshots run daily at "
                "%02d:00 PC local time; use /backup now to take one."
                % scheduled_hour(),
                ephemeral=True,
            )
            return
        latest = snapshots[0]
        await ctx.respond(
            "Latest snapshot: `%s` (%s, %d files, %.1f KB). "
            "%d snapshots stored. Scheduled snapshots run daily at "
            "%02d:00 PC local time. Restore from the web UI at /backups."
            % (
                latest["name"],
                latest["created_at"] or "unknown date",
                len(latest["files"]),
                latest["size"] / 1024,
                len(snapshots),
                scheduled_hour(),
            ),
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(Backup(bot))
