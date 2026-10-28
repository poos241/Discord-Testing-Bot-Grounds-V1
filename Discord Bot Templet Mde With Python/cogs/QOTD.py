"""Question of the Day (QOTD) cog.

Each day the bot posts one safe-for-work discussion question in a
configured channel and opens a thread on it for the day's discussion.
The next day brings a new question. No repeats until the pool is
exhausted (then the least-recently-posted questions come back around).

Design notes (read before changing this file):
- Questions live in ONE global pool (qotd_questions). Seed questions
  ship with the cog; user submissions join the pool only after a mod
  approves them, which is the SFW gate for open submissions.
- Per-guild state is separate: qotd_config (channel, time, timezone,
  enabled), qotd_history (what posted when), qotd_guild_exclusions
  (a guild's mods can remove a question from THEIR rotation without
  deleting it for everyone else).
- The scheduler is a 1-minute loop, not one timer per guild, because
  every guild can pick its own posting time. Each tick it posts for
  any guild that has no live post for today and whose scheduled time
  has passed. That single rule also gives missed-day catch-up for
  free: a bot that was offline at posting time posts within a minute
  of coming back, and never double-posts (the history row is the
  guard). A bot that comes back after several days posts only
  today's question, not a backlog.
- External question sources: researched 2026-10-27, no usable free
  QOTD API for open-ended discussion questions exists (search results
  were blog lists, not APIs; trivia APIs like Open Trivia DB are
  multiple-choice quizzes, not discussion prompts). So this cog is
  local-only by design. fetch_external_question() below is the one
  clearly-marked extension point if a real source ever shows up.
"""

import re
import random
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands, tasks

from config import GUILD_IDS
from data.DB.db import database
from data.DB.Storage.storage import (
    get_qotd_config,
    save_qotd_config,
    list_qotd_configs,
    list_qotd_questions,
    get_qotd_question,
    add_qotd_question,
    set_qotd_question,
    count_qotd_by_source,
    add_qotd_exclusion,
    list_qotd_exclusions,
    list_qotd_posted_ids,
    get_qotd_post_for_date,
    add_qotd_history,
    mark_qotd_history_skipped,
    get_qotd_history,
)

DEFAULT_TIMEZONE = "America/Chicago"
DEFAULT_POST_TIME = "09:00"

# Curated timezone choices for the /qotd config selector. Autocomplete
# filters by prefix, so typing "Europe/L" offers Europe/London, etc.
# Free text still works for any other valid IANA zone (validated below).
QOTD_TIMEZONES = [
    "America/Chicago", "America/New_York", "America/Denver",
    "America/Los_Angeles", "America/Anchorage", "Pacific/Honolulu",
    "America/Phoenix", "America/Toronto", "America/Vancouver",
    "America/Montreal", "America/Winnipeg", "America/Halifax",
    "America/Mexico_City", "America/Bogota", "America/Lima",
    "America/Santiago", "America/Sao_Paulo",
    "America/Argentina/Buenos_Aires",
    "Europe/London", "Europe/Dublin", "Europe/Paris", "Europe/Berlin",
    "Europe/Madrid", "Europe/Amsterdam", "Europe/Stockholm",
    "Europe/Warsaw", "Europe/Athens", "Europe/Moscow", "Europe/Istanbul",
    "Africa/Cairo", "Africa/Lagos", "Africa/Johannesburg", "Africa/Nairobi",
    "Asia/Dubai", "Asia/Riyadh", "Asia/Jerusalem", "Asia/Karachi",
    "Asia/Kolkata", "Asia/Dhaka", "Asia/Bangkok", "Asia/Jakarta",
    "Asia/Singapore", "Asia/Manila", "Asia/Shanghai", "Asia/Taipei",
    "Asia/Hong_Kong", "Asia/Tokyo", "Asia/Seoul",
    "Australia/Sydney", "Australia/Melbourne", "Australia/Brisbane",
    "Australia/Perth", "Australia/Adelaide", "Pacific/Auckland",
]


async def qotd_timezone_autocomplete(ctx: discord.AutocompleteContext):
    """Timezone picker suggestions, capped at Discord's 25-choice limit."""
    query = (ctx.value or "").lower()
    return [z for z in QOTD_TIMEZONES if z.lower().startswith(query)][:25]
EMBED_COLOR = 0x5865F2
QUESTION_MIN_LEN = 10
QUESTION_MAX_LEN = 500
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def safe_zoneinfo(name):
    """ZoneInfo or the default when the name is unknown."""
    try:
        return ZoneInfo(name or DEFAULT_TIMEZONE)
    except Exception:
        return ZoneInfo(DEFAULT_TIMEZONE)


def parse_post_time(value):
    """'HH:MM' (24-hour) -> datetime.time, or None when invalid."""
    m = _TIME_RE.match((value or "").strip())
    if not m:
        return None
    return dtime(int(m.group(1)), int(m.group(2)))


def is_mod(ctx):
    """Manage Messages or Administrator, matching this bot's mod checks."""
    if ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


async def fetch_external_question():
    """Extension point for a future external QOTD source.

    Returns a question string, or None. Right now it always returns
    None (local-only pool): no usable free discussion-question API
    was found at build time. To wire one in later, fetch from the
    source here, validate it is non-empty SFW text, and return it;
    the caller treats it as a seed-style question and never lets a
    fetch failure break the daily post (the local pool is the
    fallback, and a failed fetch just means the local pool is used).
    """
    return None


SEED_QUESTIONS = [
    # Favorites
    "What's a song you could listen to on repeat and never get tired of?",
    "What's your favorite cozy thing to do on a rainy day?",
    "What's a movie you can quote way too much of?",
    "What's your favorite snack to share with friends?",
    "What's a game you always come back to, no matter what else you play?",
    "What's your favorite season, and what makes it the best one?",
    "What's a book or show you wish you could experience again for the first time?",
    "What's your favorite place to just sit and relax?",
    "What's a food you could eat every single week and never get bored of?",
    "What's your favorite way to spend a lazy weekend afternoon?",
    # Hypotheticals
    "If you could have any fictional creature as a pet, what would you pick and why?",
    "If you could instantly learn any skill, what would it be?",
    "If you could live in any fictional world for a week, where would you go?",
    "If you had a free plane ticket to anywhere tomorrow, where would you go?",
    "If you could swap lives with anyone for a day, who would it be?",
    "If you could only keep three apps on your phone, which three survive?",
    "If your life had a theme song that played whenever you walked into a room, what would it be?",
    "If you could time travel to any era just to visit for a day, when would you pick?",
    "If you could have dinner with any three people, real or fictional, who would you invite?",
    "If you won a small lottery - enough for one big treat, not enough to retire - what would you spend it on?",
    "If animals could talk, which animal do you think would be the funniest to chat with?",
    "If you could add one room to your home, no matter how impossible, what would it be?",
    # Stories and memories
    "What's a small moment from this week that made you smile?",
    "What's something you were really proud of as a kid?",
    "What's the best piece of advice someone ever gave you?",
    "What's a hobby you picked up that surprised you by how much you loved it?",
    "What's a trip or outing you still think about fondly?",
    "What's something you taught yourself that you're glad you learned?",
    "What's a funny misunderstanding you've had that you can laugh about now?",
    "What's a tradition - big or small - that you love?",
    # Creative
    "If you were designing your dream cozy room, what would be in it?",
    "If you could invent a brand-new holiday, what would it celebrate?",
    "If you had to describe yourself as a flavor of ice cream, what flavor would you be and why?",
    "If you could make a playlist for a road trip with friends, what would be the first song on it?",
    "If you were a character in a cozy video game, what would your little job in the village be?",
    "If you could paint the sky any color for one day, what color would you pick?",
    "If you were writing a story about this server, what would the opening line be?",
    "If you could build a treehouse with unlimited supplies, what would it look like?",
    # Would you rather
    "Would you rather always be a little too warm or a little too cold?",
    "Would you rather explore the deep ocean or outer space?",
    "Would you rather be able to fly or turn invisible?",
    "Would you rather have a personal chef or a personal chauffeur?",
    "Would you rather read minds or see one day into the future?",
    "Would you rather live in a treehouse or a houseboat?",
    "Would you rather always have to sing instead of speak, or dance everywhere you go?",
    "Would you rather find a hidden room in your home or a hidden trail in your neighborhood?",
    # Cozy and community
    "What's something kind a stranger has done for you that you still remember?",
    "What's your go-to comfort show when you need a pick-me-up?",
    "What's a small thing someone can do that instantly makes your day better?",
    "What's a skill you'd love to learn just for fun, with no pressure to be good at it?",
    "What's your ideal way to celebrate a small win?",
    "What's a place in your town or city you'd recommend to a visitor?",
    "What's something you're looking forward to, big or small?",
    "What's a question you love being asked because you always have a fun answer?",
    # Gaming and VRChat-friendly
    "If you could step into any video game world for real, which one would you choose?",
    "What's your favorite kind of avatar or character to play as, and why?",
    "What's a game moment that made you laugh out loud?",
    "If you could design your own VRChat world, what would be in it?",
    "What's a co-op game you think everyone should try at least once?",
    "What's your favorite in-game outfit or cosmetic you've ever had?",
]

class QOTD(commands.Cog):
    """Question of the Day: one SFW discussion question per day, per server."""

    qotd = SlashCommandGroup("qotd", "Question of the Day", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        self._posting = set()
        self.qotd_loop.start()

    # ---------- internals ----------

    async def seed_if_empty(self):
        """Insert the starter pool once, the first time the cog runs."""
        try:
            if await count_qotd_by_source("seed"):
                return
            for text in SEED_QUESTIONS:
                await add_qotd_question(text, source="seed", status="approved")
            print(f"[QOTD] Seeded {len(SEED_QUESTIONS)} starter questions.")
        except Exception as e:
            print(f"[QOTD] Seeding failed: {e!r}")

    async def pick_question(self, guild_id):
        """Random approved question with no repeats until the pool is
        exhausted for this guild, then least-recently-posted first.
        Returns a question dict, or None when nothing is available."""
        approved = [q for q in await list_qotd_questions("approved") if q.get("active")]
        if not approved:
            return None
        posted = set(await list_qotd_posted_ids(guild_id))
        excluded = set(await list_qotd_exclusions(guild_id))
        fresh = [q for q in approved if q["id"] not in posted and q["id"] not in excluded]
        if fresh:
            return random.choice(fresh)
        pool = [q for q in approved if q["id"] not in excluded]
        if not pool:
            return None
        history = await get_qotd_history(guild_id, limit=10000)
        last_posted = {}
        for row in history:
            last_posted.setdefault(row["question_id"], row["posted_date"])
        pool.sort(key=lambda q: last_posted.get(q["id"], ""))
        return pool[0]

    def guild_today(self, cfg):
        tz = safe_zoneinfo(cfg.get("timezone") or DEFAULT_TIMEZONE)
        return datetime.now(tz).date().isoformat(), tz

    async def live_post_for_today(self, guild_id, cfg):
        """Today's live history row, or {} when there is none (a skipped
        row with no replacement does not count as live)."""
        today, _tz = self.guild_today(cfg)
        row = await get_qotd_post_for_date(guild_id, today)
        if row and not row.get("skipped"):
            return row
        return {}

    async def post_for_guild(self, guild_id, allow_replace=False):
        """Post today's question for one guild. Returns (ok, detail)."""
        cfg = await get_qotd_config(guild_id)
        if not cfg.get("channel_id"):
            return False, "No QOTD channel is configured. A mod can set one with /qotd config."
        if not cfg.get("enabled", True):
            return False, "QOTD is disabled for this server. A mod can re-enable it with /qotd config."
        guild = self.bot.get_guild(int(guild_id))
        if guild is None:
            return False, "Bot is not in that server."
        channel = guild.get_channel(int(cfg["channel_id"]))
        if channel is None:
            return False, "The configured QOTD channel no longer exists. A mod can pick a new one with /qotd config."
        if not allow_replace and await self.live_post_for_today(guild_id, cfg):
            return False, "Today's question is already posted."
        question = await self.pick_question(guild_id)
        if question is None:
            return False, "No approved questions are available right now."
        today, _tz = self.guild_today(cfg)
        embed = discord.Embed(
            title="Question of the Day",
            description=question["text"],
            color=EMBED_COLOR,
        )
        embed.set_footer(text=f"{today} - Reply in the thread below!")
        try:
            msg = await channel.send(embed=embed)
        except Exception as e:
            return False, f"Could not send to that channel: {e!r}"
        thread_id = ""
        try:
            thread = await msg.create_thread(
                name=f"QOTD - {today}", auto_archive_duration=1440
            )
            thread_id = str(thread.id)
        except Exception as e:
            print(f"[QOTD] Thread create failed for guild {guild_id}: {e!r}")
        await add_qotd_history(guild_id, question["id"], today, str(msg.id), thread_id)
        return True, question["text"]

    # ---------- scheduler ----------

    @tasks.loop(minutes=1)
    async def qotd_loop(self):
        for cfg in await list_qotd_configs():
            gid = cfg["guild_id"]
            if not cfg.get("enabled", True) or not cfg.get("channel_id"):
                continue
            if gid in self._posting:
                continue
            if await self.live_post_for_today(gid, cfg):
                continue
            sched = parse_post_time(cfg.get("post_time") or DEFAULT_POST_TIME)
            if sched is None:
                continue
            tz = safe_zoneinfo(cfg.get("timezone") or DEFAULT_TIMEZONE)
            if datetime.now(tz).time() < sched:
                continue
            self._posting.add(gid)
            try:
                ok, detail = await self.post_for_guild(gid)
                if not ok:
                    print(f"[QOTD] Scheduled post skipped for guild {gid}: {detail}")
            except Exception as e:
                print(f"[QOTD] Scheduled post failed for guild {gid}: {e!r}")
            finally:
                self._posting.discard(gid)

    @qotd_loop.before_loop
    async def before_qotd_loop(self):
        await self.bot.wait_until_ready()
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[QOTD] DB connect check failed: {e!r}")
        await self.seed_if_empty()

    # ---------- member commands ----------

    @qotd.command(name="today", description="Show today's Question of the Day.")
    async def qotd_today(self, ctx):
        if ctx.guild is None:
            await ctx.respond("QOTD commands only work in a server.", ephemeral=True)
            return
        cfg = await get_qotd_config(ctx.guild.id)
        row = await self.live_post_for_today(ctx.guild.id, cfg)
        if not row:
            await ctx.respond(
                "No question has been posted yet today. A mod can post one with /qotd post.",
                ephemeral=True,
            )
            return
        question = await get_qotd_question(row["question_id"])
        embed = discord.Embed(
            title="Question of the Day",
            description=question.get("text", "") if question else "",
            color=EMBED_COLOR,
        )
        embed.set_footer(text=f"{row['posted_date']} - Reply in the thread below!")
        await ctx.respond(embed=embed)

    @qotd.command(name="history", description="Look back at past Questions of the Day.")
    async def qotd_history_cmd(
        self,
        ctx,
        count: discord.Option(int, "How many past questions to show (1-25)", required=False, default=7),
    ):
        if ctx.guild is None:
            await ctx.respond("QOTD commands only work in a server.", ephemeral=True)
            return
        count = max(1, min(25, count or 7))
        rows = await get_qotd_history(ctx.guild.id, limit=count)
        if not rows:
            await ctx.respond("No past questions yet.", ephemeral=True)
            return
        lines = []
        for row in rows:
            mark = " (skipped)" if row.get("skipped") else ""
            lines.append(f"**{row['posted_date']}**{mark} - {row.get('text', '')}")
        embed = discord.Embed(
            title="Past Questions of the Day",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @qotd.command(name="submit", description="Submit a question for a future Question of the Day.")
    async def qotd_submit(
        self,
        ctx,
        question: discord.Option(str, "Your question (10-500 characters)"),
    ):
        if ctx.guild is None:
            await ctx.respond("QOTD commands only work in a server.", ephemeral=True)
            return
        text = (question or "").strip()
        if len(text) < QUESTION_MIN_LEN or len(text) > QUESTION_MAX_LEN:
            await ctx.respond(
                f"Questions need to be {QUESTION_MIN_LEN}-{QUESTION_MAX_LEN} characters. Yours was {len(text)}.",
                ephemeral=True,
            )
            return
        await add_qotd_question(
            text, source="submission", submitter_id=ctx.author.id,
            submitted_guild_id=ctx.guild.id, status="pending",
        )
        await ctx.respond(
            "Thanks! Your question is waiting for mod approval before it can enter the rotation.",
            ephemeral=True,
        )

    # ---------- mod commands ----------

    @qotd.command(name="post", description="Post today's question right now (mod only).")
    async def qotd_post(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        gid = str(ctx.guild.id)
        if gid in self._posting:
            await ctx.respond("A post for this server is already in progress.", ephemeral=True)
            return
        self._posting.add(gid)
        try:
            ok, detail = await self.post_for_guild(gid)
        finally:
            self._posting.discard(gid)
        if ok:
            await ctx.respond(f"Posted today's question: {detail}", ephemeral=True)
        else:
            await ctx.respond(detail, ephemeral=True)

    @qotd.command(name="skip", description="Replace today's question with a fresh one (mod only).")
    async def qotd_skip(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        gid = str(ctx.guild.id)
        cfg = await get_qotd_config(gid)
        row = await self.live_post_for_today(gid, cfg)
        had_live = row is not None and bool(row)
        if had_live:
            await mark_qotd_history_skipped(row["id"])
        if gid in self._posting:
            await ctx.respond("A post for this server is already in progress.", ephemeral=True)
            return
        self._posting.add(gid)
        try:
            ok, detail = await self.post_for_guild(gid, allow_replace=True)
        finally:
            self._posting.discard(gid)
        if ok:
            if had_live:
                await ctx.respond(f"Skipped today's question and posted a fresh one: {detail}", ephemeral=True)
            else:
                await ctx.respond(f"No live question today, so one was posted: {detail}", ephemeral=True)
        else:
            await ctx.respond(detail, ephemeral=True)

    @qotd.command(name="config", description="Set the QOTD channel, time, timezone, or on/off (mod only).")
    async def qotd_config_cmd(
        self,
        ctx,
        channel: discord.Option(discord.TextChannel, "Channel to post the daily question in", required=False, default=None),
        post_time: discord.Option(str, "Time of day as HH:MM, 24-hour (e.g. 09:00)", required=False, default=None),
        timezone: discord.Option(str, "Timezone (start typing to pick, e.g. Europe/London)", required=False, default=None, autocomplete=qotd_timezone_autocomplete),
        enabled: discord.Option(bool, "Turn daily posting on or off", required=False, default=None),
    ):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        gid = str(ctx.guild.id)
        cfg = await get_qotd_config(gid)
        payload = {
            "channel_id": cfg.get("channel_id", ""),
            "post_time": cfg.get("post_time", DEFAULT_POST_TIME),
            "timezone": cfg.get("timezone", DEFAULT_TIMEZONE),
            "enabled": cfg.get("enabled", True),
        }
        if channel is not None:
            payload["channel_id"] = str(channel.id)
        if post_time is not None:
            if parse_post_time(post_time) is None:
                await ctx.respond("Time must look like HH:MM in 24-hour form, e.g. 09:00 or 18:30.", ephemeral=True)
                return
            payload["post_time"] = post_time.strip()
        if timezone is not None:
            try:
                ZoneInfo(timezone.strip())
            except Exception:
                await ctx.respond(
                    "That timezone was not recognized. Try one like America/Chicago, America/New_York, or Europe/London.",
                    ephemeral=True,
                )
                return
            payload["timezone"] = timezone.strip()
        if enabled is not None:
            payload["enabled"] = bool(enabled)
        await save_qotd_config(gid, payload)
        channel_name = f"<#{payload['channel_id']}>" if payload["channel_id"] else "(none set)"
        await ctx.respond(
            f"QOTD config saved: channel {channel_name}, time {payload['post_time']} "
            f"({payload['timezone']}), enabled: {'yes' if payload['enabled'] else 'no'}.",
            ephemeral=True,
        )

    @qotd.command(name="pending", description="List submitted questions waiting for approval (mod only).")
    async def qotd_pending(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        rows = await list_qotd_questions("pending")
        if not rows:
            await ctx.respond("No questions are waiting for approval.", ephemeral=True)
            return
        lines = []
        for row in rows[:25]:
            text = row["text"]
            if len(text) > 120:
                text = text[:117] + "..."
            lines.append(f"**#{row['id']}** - {text}")
        embed = discord.Embed(
            title="Questions awaiting approval",
            description="\n".join(lines),
            color=EMBED_COLOR,
        )
        embed.set_footer(text="Approve with /qotd approve <id>, reject with /qotd reject <id>.")
        await ctx.respond(embed=embed, ephemeral=True)

    @qotd.command(name="approve", description="Approve a submitted question into the rotation (mod only).")
    async def qotd_approve(
        self,
        ctx,
        question_id: discord.Option(int, "The pending question's #id from /qotd pending"),
    ):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        row = await get_qotd_question(question_id)
        if not row:
            await ctx.respond(f"No question with id #{question_id}.", ephemeral=True)
            return
        if row.get("status") != "pending":
            await ctx.respond(f"Question #{question_id} is not pending (status: {row.get('status')}).", ephemeral=True)
            return
        await set_qotd_question(question_id, status="approved")
        await ctx.respond(f"Approved question #{question_id} into the rotation.", ephemeral=True)

    @qotd.command(name="reject", description="Reject a submitted question (mod only).")
    async def qotd_reject(
        self,
        ctx,
        question_id: discord.Option(int, "The pending question's #id from /qotd pending"),
    ):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        row = await get_qotd_question(question_id)
        if not row:
            await ctx.respond(f"No question with id #{question_id}.", ephemeral=True)
            return
        if row.get("status") != "pending":
            await ctx.respond(f"Question #{question_id} is not pending (status: {row.get('status')}).", ephemeral=True)
            return
        await set_qotd_question(question_id, status="rejected")
        await ctx.respond(f"Rejected question #{question_id}.", ephemeral=True)

    @qotd.command(name="remove", description="Remove a question from this server's rotation (mod only).")
    async def qotd_remove(
        self,
        ctx,
        question_id: discord.Option(int, "The question's #id (from history or a post)"),
    ):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        row = await get_qotd_question(question_id)
        if not row:
            await ctx.respond(f"No question with id #{question_id}.", ephemeral=True)
            return
        await add_qotd_exclusion(ctx.guild.id, question_id)
        await ctx.respond(
            f"Question #{question_id} will no longer be picked for this server. "
            "This does not delete an already-posted message, and it does not affect other servers.",
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(QOTD(bot))
