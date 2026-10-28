# cogs/TimeCmd.py
""" /time command (built 2026-10-28).

Shows a member's local time, read from the timezone they already set
on their web profile (the same 41-zone IANA list offered on the
profile edit page, stored in the profiles table's `timezone` column).
No new data is collected and no new table is needed -- this cog only
reads through the existing get_profile() storage helper.

Commands (guild-scoped, no special permissions):

  - /time [user] -- show that member's local time. With no user
    given, shows your own. The reply is public so the asker can
    share it in the channel.

How the time is resolved:

  - The target's profile row is fetched by Discord user ID. If there
    is no profile row, or its timezone field is empty, the command
    says so instead of guessing.
  - The stored IANA name is fed to zoneinfo.ZoneInfo (tzdata is
    already in requirements.txt, so this works on Windows too) and
    the current time is formatted in that zone. Discord's <t:>
    timestamp markup is deliberately NOT used here: it renders in
    the viewer's own timezone, which would show the wrong time for
    anyone in a different zone than the target.
  - A stored name ZoneInfo rejects (the edit page only accepts the
    41 known zones, so this should not happen) is reported as an
    unrecognized timezone rather than crashing or falling back to
    some other zone.

Privacy (follows the profile opt-in pattern): a member's timezone is
only shown to someone else when that member opted in with the
profile's show_local_info toggle -- the same toggle that gates the
local-time line on public profile pages. Looking up your own time
is never gated: it is your own data, and the reply tells you how to
set a timezone if you have not set one yet. Bots have no profiles,
so /time on a bot says so plainly.

What is deliberately left out: no /time for a timezone name typed
in by hand (the spec is profile timezones only), no DM delivery, and
no "time difference from you" line -- that can be added later if
Emily wants it.
"""
import datetime

import discord
from discord.ext import commands
from zoneinfo import ZoneInfo

from config import GUILD_IDS, extra_help
from data.DB.db import database
from data.DB.Storage.storage import get_profile


def _format_offset(offset):
    """timedelta -> 'UTC-05:00' style string."""
    total_seconds = int(offset.total_seconds())
    sign = "+" if total_seconds >= 0 else "-"
    total_seconds = abs(total_seconds)
    hours, remainder = divmod(total_seconds, 3600)
    minutes = remainder // 60
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


class TimeCmd(commands.Cog):
    """Show a member's local time from their profile timezone."""

    def __init__(self, bot):
        self.bot = bot

    # ---------- internals ----------

    async def _ensure_db(self):
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[TimeCmd] DB connect check failed: {e!r}")

    # ---------- commands ----------

    @discord.slash_command(name="time",
                           description="Show a member's local time from their profile timezone.",
                           guild_ids=GUILD_IDS)
    @extra_help("User: the member to look up (blank shows your own time). Reads the timezone from their web profile; if they have not set one, the command says so instead of guessing. Someone else's time is only shown when they opted in to sharing local info on their profile; your own time is always shown to you.")
    async def time_cmd(
            self, ctx,
            user: discord.Option(discord.Member, "Member whose local time to show (blank for yourself)", required=False, default=None)):
        if ctx.guild is None:
            return await ctx.respond(
                "The /time command only works in a server.",
                ephemeral=True)
        target = user or ctx.author
        if target.bot:
            return await ctx.respond(
                f"{target.display_name} is a bot and does not have a profile timezone.",
                ephemeral=True)
        await self._ensure_db()
        profile = await get_profile(str(target.id))
        tz_name = (profile.get("timezone") or "").strip()
        if not tz_name:
            if target.id == ctx.author.id:
                return await ctx.respond(
                    "You have not set a timezone on your profile yet. "
                    "Set one on the profile edit page and /time will use it.",
                    ephemeral=True)
            return await ctx.respond(
                f"{target.display_name} has not set a timezone on their profile yet.",
                ephemeral=True)
        # Privacy: another member's local info is opt-in, matching
        # the public-profile rule for timezone/location/country.
        if target.id != ctx.author.id and not profile.get("show_local_info"):
            return await ctx.respond(
                f"{target.display_name} has not opted in to sharing their local info, "
                "so their timezone is not shown here.",
                ephemeral=True)
        try:
            tz = ZoneInfo(tz_name)
        except Exception:
            return await ctx.respond(
                f"{target.display_name}'s stored timezone ({tz_name}) is not recognized. "
                "Ask them to re-pick it on the profile edit page.",
                ephemeral=True)
        now = datetime.datetime.now(tz)
        await ctx.respond(
            f"It is **{now.strftime('%I:%M %p')}** on **{now.strftime('%A, %B %d, %Y')}** "
            f"for {target.display_name} ({tz_name}, {_format_offset(now.utcoffset())}).")


def setup(bot):
    bot.add_cog(TimeCmd(bot))
