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

from config import GUILD_IDS, WORKER_MODE
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

# SIEL Project - https://thesielproject.com/question-of-the-day-for-students.html
# 180 questions, explicitly "free to use as it is, with nothing to sign up
# for or download". Kept verbatim; the school-specific and near-duplicate
# questions were dropped during curation (see the work-dir README).
SIEL_QUESTIONS = [
    "What is the best pizza topping?",
    "What is the best breakfast food?",
    "What is the best ice cream flavor?",
    "What is a food you refuse to eat?",
    "What is a vegetable you actually like?",
    "What is the best sandwich?",
    "What is the most underrated fruit?",
    "What is the best kind of cookie?",
    "What is the best day of the week?",
    "What is the best month of the year?",
    "Which season would you keep all year?",
    "What is your favorite kind of weather?",
    "What is your favorite word?",
    "What is a word you say a lot?",
    "What is a sound you love?",
    "What is a sound you cannot stand?",
    "What is a smell that puts you in a good mood?",
    "What animal would make the worst pet?",
    "What animal would you be for a day?",
    "What is the best name for a dog?",
    "What would you name a goldfish?",
    "What is the most useful invention ever?",
    "What is a job you would be terrible at?",
    "What is a job you would be great at?",
    "What is a sport you would like to try?",
    "What is the best game to play with a group?",
    "What is the most useful emoji?",
    "What is the best thing to doodle?",
    "What is a song that everyone knows?",
    "What is the best thing about being your age?",
    "What is your favorite number?",
    "What is your favorite shape?",
    "Pizza or tacos?",
    "Morning or night?",
    "Cats or dogs?",
    "Summer or winter?",
    "Books or movies?",
    "Sweet or salty?",
    "Call or text?",
    "Pancakes or waffles?",
    "City or countryside?",
    "Numbers or words?",
    "Comedy or scary movie?",
    "Sunrise or sunset?",
    "Breakfast or dinner?",
    "Inside or outside?",
    "Plan everything or make it up as you go?",
    "Talk or listen?",
    "A big group or a few people?",
    "Rain or snow?",
    "Music or quiet while you work?",
    "Pen or pencil?",
    "Cook or clean up?",
    "Spicy or mild?",
    "Video games or board games?",
    "Popcorn or chips?",
    "Ask for directions or figure it out yourself?",
    "Lead the group or help the leader?",
    "Early or right on time?",
    "Draw or write?",
    "Would you rather be able to talk to animals or speak every human language?",
    "What would be the most annoying superpower to have?",
    "If animals could talk, which one would be the rudest?",
    "What is something popular that you do not understand?",
    "Would you rather have a pause button or a rewind button for your life?",
    "What is the strangest food combination you actually like?",
    "If you could only eat food of one color for a week, which color would you pick?",
    "What would you do with an extra hour every day?",
    "Would you rather be the funniest person in the room or the smartest?",
    "What everyday object would be the scariest if it were giant?",
    "If you opened a store tomorrow, what would it sell?",
    "What everyday skill should be an Olympic sport?",
    "What job should robots do instead of people?",
    "Would you rather never need to sleep or never need to eat?",
    "If you were a kitchen appliance, which one would you be?",
    "Would you rather travel 100 years into the past or 100 years into the future?",
    "What would be the best surprise to find on your desk tomorrow?",
    "If you could make one chore disappear forever, which one would it be?",
    "If you could rename this town, what would you call it?",
    "What would be the worst flavor for toothpaste?",
    "If you could shrink to the size of an ant for an hour, what would you do?",
    "What is a word that sounds funny to you?",
    "What is a question you wish people asked you more often?",
    "If you could ask anyone from history one question, what would you ask?",
    "What makes a good teammate?",
    "What is something that is harder than it looks?",
    "What is something that is easier than it looks?",
    "What makes a place feel welcoming?",
    "What is something you used to be scared of that does not scare you now?",
    "What does a good listener do?",
    "What invention do you think will exist in 20 years?",
    "Which is more important, being liked or being respected?",
    "What makes something funny?",
    "What is a small thing a stranger could do to make someone's day better?",
    "What problem in the world would you most like to solve?",
    "What skill do you think will matter more in the future than it does now?",
    "How can you tell when you really understand something?",
    "What is a rule that makes sense, even if you do not like it?",
    "If you wrote a book, what would it be about?",
    "What makes a good apology?",
    "What is a good way to start a conversation with someone you do not know?",
    "What is the best way to remember something important?",
    "What is something you think is worth waiting for?",
    "Why do you think people enjoy scary movies?",
    "What is something you figured out on your own recently?",
    "Who is someone that deserves a thank you this week, and why?",
    "What is a skill you have taught someone else?",
    "What is something you are curious about right now?",
    "What helps you calm down when you are stressed?",
    "What is one goal you have for this week?",
    "What is something kind someone did for you recently?",
    "What is something you are better at now than you were last year?",
    "Where is a place you feel most like yourself?",
    "What do you like to do when you have nothing to do?",
    "What is something you want to learn how to do?",
    "What made you laugh recently?",
    "What is something you do that helps other people?",
    "What is something you are not good at yet?",
    "What does a good day look like for you?",
    "What have you been practicing lately?",
    "What is one thing you know now that you wish you had known last year?",
    "How do you like to celebrate when something goes well?",
    "What is something that is easier to do with other people than alone?",
    "What is a compliment that would make your day?",
    "If today were a kind of weather, what would it be?",
    "What color matches your mood today?",
    "For a Monday: what is one word for how you are starting the week?",
    "For a Friday: what was the best part of your week?",
    "Which emoji matches how you feel right now?",
    "What would help you focus today?",
    "Ready, unsure or need a minute: which one are you today?",
    "What song title describes your day so far?",
    "Chatty or quiet today?",
    "What do you need more of this week: rest, help or time?",
    "Is today a \"go fast\" day or a \"go slow\" day for you?",
    "What is one thing you are proud of from yesterday?",
    "Water, snack or nap: which do you need most right now?",
    "Is it better to have a few close friends or a lot of friends you know a little?",
    "What makes someone a good leader?",
    "Can a person be confident and humble at the same time?",
    "Is it ever right to break a rule? When?",
    "Does social media bring people closer together or push them apart?",
    "When you cannot be both, is it better to be honest or kind?",
    "Should people always say what they think?",
    "What makes a conversation feel easy instead of awkward?",
    "Is it more important to be good at something or to enjoy it?",
]

# Conversation Starters World - https://conversationstartersworld.com/question-of-the-day/
# No license is stated on the site, so this is a curated selection with
# attribution, not a wholesale copy. Kept verbatim; the class and kids
# sets were dropped, as were the playful-dark friends/funny questions.
CSW_QUESTIONS = [
    "What are the unwritten rules of where you work?",
    "What is the funniest corporate / business screw up you have heard of?",
    "What’s some insider knowledge that only people in your line of work have?",
    "What’s the weirdest thing that has happened to you while working at your job?",
    "What tips or tricks have you picked up from your job / jobs?",
    "What job are you grossly underqualified for but think you would be pretty good at?",
    "What profession doesn’t get enough credit or respect?",
    "What question do people always ask you once they find out what you do?",
    "Presentation: Go First or Go Last?",
    "Would you rather live without the internet or live without AC and heating?",
    "Would you rather never lose your phone again or never lose your keys again?",
    "Would you rather follow the instructions on how to do something or try without instructions?",
    "Would you rather do a physically hard job for a day or a boring job for a week?",
    "When you have a problem would you rather talk with someone or try to figure it out by yourself?",
    "What invention doesn’t get a lot of love, but has greatly improved the world?",
    "What really needs to be modernized?",
    "What product do you wish a company would make a “smart” version of?",
    "If you could be an NPC in any videogame, what game would you choose to reside in?",
    "If you could bring back any canceled TV series, which TV show would you choose to bring back?",
    "If you could put a new word in the dictionary, what would it be and what would be the definition?",
    "What kind of business would you like to start if you were given a chance?",
    "What did you manage to fix with something that was absolutely not the right tool?",
    "What do you take far too seriously and that makes it take longer than it should?",
    "What ordinary errand somehow turned into an adventure?",
    "How do you feel about putting pineapple on pizza?",
    "What’s your “and then it got worse” story?",
    "Is cereal soup? Why or why not?",
    "What’s the most polarizing question you could ask a group of your friends?",
    "Our lottery pool wins, but one person forgot to pay their dollar. How much are we giving them?",
    "In your group of friends, what role do you play?",
    "What stereotype do you completely live up to?",
    "What is a controversial opinion you have?",
    "What’s the dumbest thing someone has argued with you about?",
    "What do a lot of people have very strong opinions about, even though they know very little about it?",
    "What movie universe would be the worst to live out your life in?",
    "Which TV character would be a nightmare to share a kitchen with?",
    "You can send one harmless inconvenience to your worst enemy. What do you send?",
    "What awful movie do you love?",
    "What happens regularly that would horrify a person from 100 years ago?",
    "A tiny brass band follows you for one day. When would it be useful, and when would it be unbearable?",
    "In what situations, do you wish you could throw down a smoke bomb and disappear?",
    "What would be on the gag reel of your life?",
    "What would be the worst “buy one get one free” sale of all time?",
    "What secret conspiracy would you like to start?",
    "Think of a brand, now what would an honest slogan for that brand be?",
    "What’s the most useless talent you have?",
    "Be honest: if you were born in medieval times, you probably wouldn't be royalty or a knight. So what kind of peasant would you be?",
    "What’s the most boring super hero you can come up with?",
    "What is something that everyone looks stupid doing?",
    "Tear gas makes people cry and laughing gas makes people giggle, what other kinds of gases do you wish existed?",
    "What movie completely changes its plot when you change one letter in its title? What’s the new movie about?",
    "What would the adult version of an ice-cream truck sell and what song would it play?",
    "First think of a product. Now, what would be the absolute worst brand name for one of those products?",
    "What two totally normal things become really weird if you do them back to back?",
    "What’s the best Wi-Fi name you’ve seen?",
    "What two things are terrible when separate but great when you put them together?",
    "If you were a cursed sword, what would your owner have to shout every time they swung you?",
    "If you were a pirate captain, what petty offense would you make someone walk the plank for?",
    "If you were a ghost and could possess people, what would you make them do?",
    "What's your biggest screw up in the kitchen?",
    "What’s the most epic way you’ve seen someone quit or be fired?",
    "What’s the most ridiculous thing you have bought?",
    "What escalated very quickly?",
    "What ridiculous thing has someone tricked you into doing or believing?",
    "If you were an alien lawyer trying to get Earth demolished, what TV show would you play for the jury?",
    "If all your memories were erased, what kind of person would you be?",
    "If everyone said what they were actually thinking, what would happen to society?",
    "Is it better to be a big fish in a small pond or a small fish in a big pond?",
    "What lies do you most often tell yourself?",
    "Why do people expect a universe full of randomness to be fair?",
    "What are some of society’s unwritten rules?",
    "What is the biggest waste of human potential?",
    "Is it better for a person to have a broad knowledge base or a deep knowledge base?",
    "What life-altering things should every human ideally get to experience at least once in their lives?",
    "How much privacy are you willing to sacrifice for safety?",
    "Why is it so hard to learn from our mistakes?",
    "What’s the weirdest thing about modern life that people just accept as normal?",
    "Has social media been a net positive or a net negative for our society? Why?",
    "In general, is it better for a person to stand out and be different or blend in with everyone else?",
    "In what ways do you sabotage yourself?",
    "Is intelligence or wisdom more useful?",
    "How much effort should an individual put into not offending others?",
    "What’s something terrifying that we’ve all come to accept as a fact of life?",
    "If humanity was put on trial by an advanced race of aliens, how would you defend humanity and argue for its continued existence?",
    "Free Will or Destiny?",
    "If you had to disappear and start a whole new life, what would you want your new life to look like?",
    "What is a miracle that happens every day?",
    "If you had to sum up the whole human species in 3 words, what would those words be?",
    "Would you rather die in 20 years with no regrets or die in 50 years with many regrets?",
    "What social stigma does society need to get over?",
]

class QOTD(commands.Cog):
    """Question of the Day: one SFW discussion question per day, per server."""

    qotd = SlashCommandGroup("qotd", "Question of the Day", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        self._posting = set()
        # The daily posting loop runs ONLY on the main bot. The worker
        # loads this cog for its /qotd config command (setup,
        # worker-only since the 2026-11-12 command split, Option C);
        # if the worker ran the loop too, every question would post twice.
        if not WORKER_MODE:
            self.qotd_loop.start()

    # ---------- internals ----------

    async def seed_if_empty(self):
        """Insert each bundled pool once, the first time the cog runs.

        Each source is seeded independently: a live DB that already has
        the 60 starter questions still gets the SIEL and CSW pools on
        the next boot, and a fresh DB gets all three. Re-running inserts
        nothing (the per-source count guard makes it idempotent).
        """
        try:
            for source, questions in (
                ("seed", SEED_QUESTIONS),
                ("siel", SIEL_QUESTIONS),
                ("csw", CSW_QUESTIONS),
            ):
                if await count_qotd_by_source(source):
                    continue
                for text in questions:
                    await add_qotd_question(text, source=source, status="approved")
                print(f"[QOTD] Seeded {len(questions)} {source} questions.")
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
        try:
            configs = await list_qotd_configs()
        except Exception as e:
            print(f"[QOTD] ERROR: could not load QOTD configs: {e!r}")
            return
        for cfg in configs:
            try:
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
            except Exception as e:
                print(f"[QOTD] ERROR: scheduled check failed for guild "
                      f"{cfg.get('guild_id') if isinstance(cfg, dict) else '?'}: {e!r}")

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

    if not WORKER_MODE:
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

    if not WORKER_MODE:
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

    if not WORKER_MODE:
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

    if not WORKER_MODE:
        @qotd.command(name="post", description="Post today's question right now (mod only).")
        async def qotd_post(self, ctx):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_post", _default_manage_messages_or_admin):
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

    if not WORKER_MODE:
        @qotd.command(name="skip", description="Replace today's question with a fresh one (mod only).")
        async def qotd_skip(self, ctx):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_skip", _default_manage_messages_or_admin):
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

    if WORKER_MODE:
        @qotd.command(name="config", description="Set the QOTD channel, time, timezone, or on/off (mod only).")
        async def qotd_config_cmd(
            self,
            ctx,
            channel: discord.Option(discord.TextChannel, "Channel to post the daily question in", required=False, default=None),
            post_time: discord.Option(str, "Time of day as HH:MM, 24-hour (e.g. 09:00)", required=False, default=None),
            timezone: discord.Option(str, "Timezone (start typing to pick, e.g. Europe/London)", required=False, default=None, autocomplete=qotd_timezone_autocomplete),
            enabled: discord.Option(bool, "Turn daily posting on or off", required=False, default=None),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_config", _default_manage_messages_or_admin):
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

    if not WORKER_MODE:
        @qotd.command(name="pending", description="List submitted questions waiting for approval (mod only).")
        async def qotd_pending(self, ctx):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_pending", _default_manage_messages_or_admin):
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

    if not WORKER_MODE:
        @qotd.command(name="approve", description="Approve a submitted question into the rotation (mod only).")
        async def qotd_approve(
            self,
            ctx,
            question_id: discord.Option(int, "The pending question's #id from /qotd pending"),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_approve", _default_manage_messages_or_admin):
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

    if not WORKER_MODE:
        @qotd.command(name="reject", description="Reject a submitted question (mod only).")
        async def qotd_reject(
            self,
            ctx,
            question_id: discord.Option(int, "The pending question's #id from /qotd pending"),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_reject", _default_manage_messages_or_admin):
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

    if not WORKER_MODE:
        @qotd.command(name="remove", description="Remove a question from this server's rotation (mod only).")
        async def qotd_remove(
            self,
            ctx,
            question_id: discord.Option(int, "The question's #id (from history or a post)"),
        ):
            from utils.permissions import check_slash_permission, _default_manage_messages_or_admin
            if not await check_slash_permission(ctx, "qotd_remove", _default_manage_messages_or_admin):
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
