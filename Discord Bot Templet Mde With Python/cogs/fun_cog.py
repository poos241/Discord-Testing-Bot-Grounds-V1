# cogs/fun_cog.py
"""Fun party games for the server. First game: Eat It or Yeet It.

Rounds are persistent: votes and round state are saved to disk, the voting
buttons use stable custom_ids, and the view is re-registered on startup, so
rounds survive bot restarts and crashes. A background task finishes rounds
whose timer expired (even ones that expired while the bot was down).
"""
import random
import time

import discord
from discord.ext import commands, tasks

from config import load_json, save_json, extra_help, GUILD_IDS

STATS_FILE = "eatyeet_stats.json"
SUGGESTIONS_FILE = "eatyeet_suggestions.json"
ACTIVE_FILE = "eatyeet_active.json"  # rounds currently running (survives restarts)
START_COOLDOWN = 30  # seconds before the same user can start another round
MAX_SUGGESTIONS_PER_GUILD = 25
SUGGESTION_CHANCE = 0.25  # chance a round pulls a community-suggested food
MAX_HISTORY = 10  # rounds of history kept per guild

RARITY_EMOJI = {"common": "🟢", "weird": "🟡", "cursed": "🟣", "community": "💡"}
RARITY_POINTS = {"common": 1, "weird": 2, "cursed": 3, "community": 2}
VERDICT_EMOJI = {"eat": "😋", "yeet": "🗑️", "tie": "✨", "none": "😐"}

DURATIONS = [
    discord.OptionChoice(name="Quick test (30 seconds)", value=30),
    discord.OptionChoice(name="1 hour", value=3600),
    discord.OptionChoice(name="2 hours", value=7200),
    discord.OptionChoice(name="4 hours", value=14400),
    discord.OptionChoice(name="8 hours", value=28800),
    discord.OptionChoice(name="12 hours", value=43200),
    discord.OptionChoice(name="24 hours", value=86400),
]

# (common 50% / weird 35% / cursed 15% — when not pulling a suggestion)
FOODS = {
    "common": [
        "Cold pizza",
        "Chicken nuggets",
        "Mac and cheese",
        "A warm chocolate chip cookie",
        "Strawberry milk",
        "Pancakes with maple syrup",
        "A grilled cheese sandwich",
        "A juicy cheeseburger",
        "Tacos",
        "An ice cream sundae",
        "Fresh-baked bread",
        "Apple slices with peanut butter",
        "Mozzarella sticks",
        "A soft pretzel with cheese",
        "Banana bread",
    ],
    "weird": [
        "Pickle ice cream",
        "A spaghetti sandwich",
        "Cereal with orange juice instead of milk",
        "A whole raw onion, eaten like an apple",
        "Chocolate-covered bacon",
        "Deep-fried butter on a stick",
        "A mayonnaise popsicle",
        "Pizza with pineapple AND anchovies",
        "Ketchup on vanilla ice cream",
        "A peanut butter and pickle sandwich",
        "Cold canned sardines",
        "A ranch dressing milkshake",
        "Cheese sprayed straight from the can",
        "Microwaved gummy bears",
        "A hot dog smoothie",
    ],
    "cursed": [
        "Gas station sushi that's been sitting out all day",
        "Mystery meat from the back of the fridge",
        "Yogurt that's 3 months past its date",
        "A sandwich found under the couch",
        "Toothpaste-filled Oreos",
        "Three-week-old leftovers",
        "A popsicle that fell on the floor (5 second rule?)",
        "Pickled pig feet",
        "Limburger cheese aged in a gym bag",
        "A single dry saltine cracker (that's the whole meal)",
        "Soup made from whatever was in the junk drawer",
        "A burger that's been in a hot car since July",
        "Milk that's juuuust starting to turn",
        "An egg salad sandwich left out in the sun",
        "Sock-flavored jelly beans",
    ],
}

EAT_WINS = [
    "The crowd has spoken — DEVOURED! 😋",
    "Gone in seconds. The plate is licked clean. 🍽️",
    "A bold choice, and the people respect it. EATEN!",
    "No survivors. That food is history. 😤",
    "Inhaled. Absolutely demolished. 🍽️💨",
]

YEET_WINS = [
    "YEETED! Straight into the sun. 🗑️☀️",
    "The people have rejected it. Launched into orbit. 🚀",
    "Yeeted with extreme prejudice. Nobody wanted that. 💥",
    "Into the trash dimension it goes. 🌀",
    "YEET! It has left the building. 👋🗑️",
]

TIES = [
    "It's a perfect tie! The food ascends to a higher plane, uneaten and unyeeted. ✨",
    "Dead even! The food is spared... for now. 👀",
]

NO_VOTES = "Nobody voted... the food sits there, judging you all. 😐"


class EatYeetView(discord.ui.View):
    """Persistent voting buttons.

    timeout=None + stable custom_ids means pycord re-routes button clicks to
    this view even after a bot restart (as long as the cog re-registers it via
    bot.add_view). The view itself holds no round state — clicks are routed to
    the round by channel, and state lives in the cog (saved to disk).
    """

    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Eat it!", emoji="🍽️", style=discord.ButtonStyle.success,
                       custom_id="eatyeet:eat")
    async def eat_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.register_vote(interaction, "eat")

    @discord.ui.button(label="Yeet it!", emoji="🗑️", style=discord.ButtonStyle.danger,
                       custom_id="eatyeet:yeet")
    async def yeet_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.register_vote(interaction, "yeet")


class FunCog(commands.Cog):
    """Party games for the server."""

    def __init__(self, bot):
        self.bot = bot
        self.active = self._load_active()  # channel_id (int) -> round dict
        # NOTE: the vote view is created in _ensure_view(), NOT here.
        # discord.ui.View needs a running event loop to exist, and cogs are
        # loaded (via load_extension) before the bot's loop starts — creating
        # it here crashes with "RuntimeError: no running event loop".
        self.vote_view = None
        self._messages = {}  # channel_id -> discord.Message (in-memory cache)
        self._last_edit = {}  # channel_id -> timestamp (live-count throttle)
        self.start_cooldowns = {}  # user_id -> timestamp of last round started
        self._ready = False

    def cog_unload(self):
        self._expiry_loop.cancel()

    def _ensure_view(self):
        """Create and register the persistent vote view.

        Must be called from inside the running event loop (on_ready or a
        command) — never at import/cog-load time.
        """
        if self.vote_view is None:
            self.vote_view = EatYeetView(self)
            # Re-register the persistent buttons every startup so rounds
            # survive bot restarts and crashes.
            self.bot.add_view(self.vote_view)

    # ----- persistence -----

    def _load_active(self):
        data = load_json(ACTIVE_FILE)
        # JSON keys are strings; normalize back to ints.
        return {int(k): v for k, v in data.items()}

    def _save_active(self):
        save_json(ACTIVE_FILE, {str(k): v for k, v in self.active.items()})

    def _guild_stats(self, stats, guild_id):
        """Get (creating if needed) a guild's stats block, migrating old keys."""
        g = stats.setdefault(str(guild_id), {"rounds": 0, "users": {}, "history": []})
        migrated = False
        for u in g["users"].values():
            if "voted" in u:  # schema v1 -> v2
                u["played"] = u.pop("voted")
                migrated = True
            for key, default in (("played", 0), ("points", 0), ("majority", 0),
                                 ("streak", 0), ("best_streak", 0)):
                if key not in u:
                    u[key] = default
                    migrated = True
        if "history" not in g:
            g["history"] = []
            migrated = True
        if migrated:
            save_json(STATS_FILE, stats)
        return g

    def _get_suggestions(self, guild_id):
        data = load_json(SUGGESTIONS_FILE)
        return data.get(str(guild_id), [])

    # ----- helpers -----

    @staticmethod
    def _counts(rnd):
        votes = rnd["votes"]
        eats = sum(1 for v in votes.values() if v == "eat")
        yeets = sum(1 for v in votes.values() if v == "yeet")
        return eats, yeets

    def _pick_food(self, guild_id):
        """Returns (food_name, rarity, suggested_by_name_or_None)."""
        suggestions = self._get_suggestions(guild_id)
        if suggestions and random.random() < SUGGESTION_CHANCE:
            s = random.choice(suggestions)
            return s["food"], "community", s.get("by_name")
        roll = random.random()
        if roll < 0.15:
            rarity = "cursed"
        elif roll < 0.50:
            rarity = "weird"
        else:
            rarity = "common"
        return random.choice(FOODS[rarity]), rarity, None

    def build_round_embed(self, rnd) -> discord.Embed:
        eats, yeets = self._counts(rnd)
        points = RARITY_POINTS[rnd["rarity"]]
        desc = f"**{rnd['food']}**\n{RARITY_EMOJI[rnd['rarity']]} Rarity: **{rnd['rarity'].title()}**"
        if rnd["suggested_by"]:
            desc += f"\n💡 Suggested by **{rnd['suggested_by']}**"
        embed = discord.Embed(
            title="🍽️ EAT IT or YEET IT 🗑️",
            description=desc,
            color=0x9B59B6,
        )
        embed.add_field(name="🍽️ Eat it", value=f"**{eats}**", inline=True)
        embed.add_field(name="🗑️ Yeet it", value=f"**{yeets}**", inline=True)
        embed.set_footer(text=f"Vote with the buttons below! You can change your vote. "
                              f"Majority voters earn {points} pt{'s' if points != 1 else ''}. "
                              f"Voting ends <t:{int(rnd['ends_at'])}:R>")
        return embed

    def build_results_embed(self, rnd, verdict, shoutouts) -> discord.Embed:
        eats, yeets = self._counts(rnd)
        score = f"🍽️ **{eats}** — 🗑️ **{yeets}**"
        if verdict == "eat":
            title, color = "😋 EATEN!", 0x2ECC71
            desc = f"**{rnd['food']}**\n{score}\n\n_{random.choice(EAT_WINS)}_"
        elif verdict == "yeet":
            title, color = "🗑️ YEETED!", 0xE74C3C
            desc = f"**{rnd['food']}**\n{score}\n\n_{random.choice(YEET_WINS)}_"
        elif verdict == "tie":
            title, color = "✨ IT'S A TIE!", 0xF1C40F
            desc = f"**{rnd['food']}**\n{score}\n\n_{random.choice(TIES)}_"
        else:
            title, color = "😐 Nobody voted", 0x95A5A6
            desc = f"**{rnd['food']}**\n\n_{NO_VOTES}_"
        embed = discord.Embed(title=title, description=desc, color=color)
        # Voter roll-call (capped so big rounds don't blow up the embed).
        if rnd["votes"]:
            eat_names = [rnd["voter_names"].get(uid, "Someone")
                         for uid, v in rnd["votes"].items() if v == "eat"][:12]
            yeet_names = [rnd["voter_names"].get(uid, "Someone")
                          for uid, v in rnd["votes"].items() if v == "yeet"][:12]
            if eat_names:
                extra = f" +{len([1 for v in rnd['votes'].values() if v == 'eat']) - len(eat_names)} more" \
                    if len([1 for v in rnd["votes"].values() if v == "eat"]) > len(eat_names) else ""
                embed.add_field(name=f"🍽️ Ate it ({len([1 for v in rnd['votes'].values() if v == 'eat'])})",
                                value=", ".join(eat_names) + extra, inline=False)
            if yeet_names:
                extra = f" +{len([1 for v in rnd['votes'].values() if v == 'yeet']) - len(yeet_names)} more" \
                    if len([1 for v in rnd["votes"].values() if v == "yeet"]) > len(yeet_names) else ""
                embed.add_field(name=f"🗑️ Yeeted it ({len([1 for v in rnd['votes'].values() if v == 'yeet'])})",
                                value=", ".join(yeet_names) + extra, inline=False)
        if shoutouts:
            embed.add_field(name="Streaks", value="\n".join(
                f"🔥 **{name}** is on a {streak}-round streak!" for name, streak in shoutouts),
                inline=False)
        return embed

    def _tally_and_save(self, rnd):
        """Decide the verdict, award points/streaks, save stats + history.

        Returns (verdict, shoutouts). Pure logic — no Discord calls."""
        eats, yeets = self._counts(rnd)
        if eats == 0 and yeets == 0:
            verdict = "none"
        elif eats > yeets:
            verdict = "eat"
        elif yeets > eats:
            verdict = "yeet"
        else:
            verdict = "tie"

        majority_voters = set()
        if verdict in ("eat", "yeet"):
            majority_voters = {uid for uid, vote in rnd["votes"].items() if vote == verdict}

        stats = load_json(STATS_FILE)
        guild_stats = self._guild_stats(stats, rnd["guild_id"])
        guild_stats["rounds"] += 1
        for user_id, vote in rnd["votes"].items():
            u = guild_stats["users"].setdefault(str(user_id), {
                "played": 0, "points": 0, "majority": 0, "streak": 0, "best_streak": 0,
            })
            u["played"] += 1
            if user_id in majority_voters:
                u["majority"] += 1
                u["points"] += RARITY_POINTS[rnd["rarity"]]
                u["streak"] += 1
                u["best_streak"] = max(u["best_streak"], u["streak"])
            else:
                u["streak"] = 0
        guild_stats["history"].append({
            "food": rnd["food"],
            "verdict": verdict,
            "eats": eats,
            "yeets": yeets,
            "ended_at": time.time(),
        })
        guild_stats["history"] = guild_stats["history"][-MAX_HISTORY:]
        save_json(STATS_FILE, stats)

        shoutouts = []
        for uid in majority_voters:
            u = guild_stats["users"][str(uid)]
            if u["streak"] >= 3:
                shoutouts.append((rnd["voter_names"].get(uid, "Someone"), u["streak"]))
        shoutouts.sort(key=lambda x: x[1], reverse=True)
        return verdict, shoutouts[:3]

    # ----- voting -----

    async def register_vote(self, interaction: discord.Interaction, choice: str):
        """Button callback entry point — routes the click to the live round."""
        channel_id = interaction.channel_id
        rnd = self.active.get(channel_id) if channel_id else None
        if rnd is None:
            await interaction.response.send_message("That round has already ended!", ephemeral=True)
            return
        if interaction.message is not None and interaction.message.id != rnd["message_id"]:
            await interaction.response.send_message("That round has already ended!", ephemeral=True)
            return
        uid = str(interaction.user.id)
        rnd["votes"][uid] = choice
        rnd["voter_names"][uid] = getattr(interaction.user, "display_name", "Someone")
        self._save_active()
        word = "EAT IT 🍽️" if choice == "eat" else "YEET IT 🗑️"
        await interaction.response.send_message(
            f"You voted **{word}** for {rnd['food']}!",
            ephemeral=True,
        )
        await self._refresh_counts(channel_id)

    async def _fetch_message(self, rnd):
        """Fetch the round's message from Discord (None if gone)."""
        channel = self.bot.get_channel(rnd["channel_id"])
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(rnd["channel_id"])
            except discord.HTTPException:
                return None
        try:
            return await channel.fetch_message(rnd["message_id"])
        except discord.HTTPException:
            return None

    async def _get_message(self, channel_id: int):
        if channel_id in self._messages:
            return self._messages[channel_id]
        rnd = self.active.get(channel_id)
        if rnd is None:
            return None
        message = await self._fetch_message(rnd)
        if message is not None:
            self._messages[channel_id] = message
        return message

    async def _refresh_counts(self, channel_id: int):
        # Throttled live update of the vote counts (avoids rate limits).
        if channel_id not in self.active:
            return
        now = time.time()
        if now - self._last_edit.get(channel_id, 0) < 2:
            return
        self._last_edit[channel_id] = now
        message = await self._get_message(channel_id)
        if message is None:
            return
        try:
            await message.edit(embed=self.build_round_embed(self.active[channel_id]))
        except discord.HTTPException:
            pass

    # ----- finishing -----

    async def _finish_round(self, channel_id: int):
        """Finish a round: tally, save, announce, and remove the buttons."""
        rnd = self.active.pop(channel_id, None)
        if rnd is None:
            return
        self._save_active()
        self._messages.pop(channel_id, None)
        self._last_edit.pop(channel_id, None)

        verdict, shoutouts = self._tally_and_save(rnd)
        embed = self.build_results_embed(rnd, verdict, shoutouts)

        message = await self._fetch_message(rnd)
        if message is not None:
            try:
                # view=None removes the buttons from the finished round.
                await message.edit(embed=embed, view=None)
            except discord.HTTPException:
                pass

    async def _finish_expired_rounds(self):
        now = time.time()
        expired = [cid for cid, rnd in self.active.items() if rnd["ends_at"] <= now]
        for cid in expired:
            await self._finish_round(cid)

    @tasks.loop(seconds=30)
    async def _expiry_loop(self):
        await self._finish_expired_rounds()

    @_expiry_loop.before_loop
    async def _before_expiry_loop(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_ready(self):
        # (Re)start the expiry checker once, and immediately finish anything
        # that expired while the bot was down.
        if self._ready:
            return
        self._ready = True
        self._ensure_view()  # safe here: the event loop is running
        if not self._expiry_loop.is_running():
            self._expiry_loop.start()
        await self._finish_expired_rounds()

    # ----- commands -----

    @discord.slash_command(name="eatyeet", description="Start a round of Eat It or Yeet It!", guild_ids=GUILD_IDS)
    @extra_help("Starts a round of Eat It or Yeet It. Pick how long voting stays open (30s up to 24h). The bot serves up a random food, everyone votes with the buttons, and the verdict is announced when time runs out. Rounds survive bot restarts.")
    async def eatyeet(
        self,
        ctx: discord.ApplicationContext,
        duration: discord.Option(int, "How long should voting stay open?", choices=DURATIONS, default=30),  # type: ignore
    ):
        """Start a round of Eat It or Yeet It."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        if ctx.channel.id in self.active:
            await ctx.respond("There's already a round going in this channel — vote on that one first!", ephemeral=True)
            return
        now = time.time()
        last = self.start_cooldowns.get(ctx.author.id, 0)
        if now - last < START_COOLDOWN:
            wait = int(START_COOLDOWN - (now - last))
            await ctx.respond(f"Slow down! You can start another round in {wait} seconds.", ephemeral=True)
            return
        self.start_cooldowns[ctx.author.id] = now
        self._ensure_view()  # belt-and-braces: view exists if on_ready was missed

        food, rarity, suggested_by = self._pick_food(ctx.guild.id)
        rnd = {
            "guild_id": ctx.guild.id,
            "channel_id": ctx.channel.id,
            "message_id": 0,  # filled in once the message is sent
            "food": food,
            "rarity": rarity,
            "suggested_by": suggested_by,
            "starter_id": ctx.author.id,
            "ends_at": now + duration,
            "votes": {},
            "voter_names": {},
        }
        self.active[ctx.channel.id] = rnd
        self._save_active()

        await ctx.respond(embed=self.build_round_embed(rnd), view=self.vote_view)
        message = await ctx.interaction.original_response()
        rnd["message_id"] = message.id
        self._messages[ctx.channel.id] = message
        self._save_active()

    @discord.slash_command(name="eatyeet_end", description="End the current Eat It or Yeet It round early.", guild_ids=GUILD_IDS)
    @extra_help("Ends the active Eat It or Yeet It round in this channel right away. Only the person who started it (or an admin) can use this.")
    async def eatyeet_end(self, ctx: discord.ApplicationContext):
        """End the active round in this channel early."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        rnd = self.active.get(ctx.channel.id)
        if rnd is None:
            await ctx.respond("There's no active round in this channel.", ephemeral=True)
            return
        is_starter = ctx.author.id == rnd["starter_id"]
        is_admin = ctx.author.guild_permissions.administrator
        if not (is_starter or is_admin):
            await ctx.respond("Only the person who started the round (or an admin) can end it early.", ephemeral=True)
            return
        await ctx.respond("Ending the round early! Tallying the votes...", ephemeral=True)
        await self._finish_round(ctx.channel.id)

    @discord.slash_command(name="eatyeet_leaderboard", description="Show the Eat It or Yeet It leaderboard.", guild_ids=GUILD_IDS)
    @extra_help("Shows the top 10 players ranked by points. Points come from voting with the majority — rarer foods are worth more.")
    async def eatyeet_leaderboard(self, ctx: discord.ApplicationContext):
        """Show the Eat It or Yeet It leaderboard."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        stats = load_json(STATS_FILE)
        users = self._guild_stats(stats, ctx.guild.id)["users"]
        if not users:
            await ctx.respond("No rounds played yet! Start one with /eatyeet.", ephemeral=True)
            return
        ranked = sorted(users.items(), key=lambda kv: kv[1]["points"], reverse=True)[:10]
        lines = []
        for i, (user_id, s) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(int(user_id))
            name = member.display_name if member else f"<@{user_id}>"
            streak = f" 🔥{s['streak']}" if s["streak"] >= 2 else ""
            lines.append(f"**{i}.** {name} — **{s['points']}** pts "
                         f"({s['majority']}/{s['played']} majority){streak}")
        embed = discord.Embed(
            title="🏆 Eat It or Yeet It — Leaderboard",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        embed.set_footer(text="Majority vote points: common = 1, weird/community = 2, cursed = 3")
        await ctx.respond(embed=embed)

    @discord.slash_command(name="eatyeet_stats", description="Check Eat It or Yeet It stats for yourself or someone else.", guild_ids=GUILD_IDS)
    @extra_help("Shows rounds played, points, majority-vote rate, and current/best streak for a player.")
    async def eatyeet_stats(
        self,
        ctx: discord.ApplicationContext,
        user: discord.Option(discord.User, "Pick a user to check (defaults to you)", required=False, default=None),  # type: ignore
    ):
        """Check Eat It or Yeet It stats."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        target = user or ctx.author
        stats = load_json(STATS_FILE)
        s = self._guild_stats(stats, ctx.guild.id)["users"].get(str(target.id))
        name = getattr(target, "display_name", str(target.id))
        if not s or s["played"] == 0:
            await ctx.respond(f"**{name}** hasn't played any rounds yet!", ephemeral=True)
            return
        rate = round(100 * s["majority"] / s["played"]) if s["played"] else 0
        embed = discord.Embed(
            title=f"🍽️ {name}'s Eat It or Yeet It stats",
            color=0x9B59B6,
        )
        embed.add_field(name="Points", value=f"**{s['points']}**", inline=True)
        embed.add_field(name="Rounds played", value=str(s["played"]), inline=True)
        embed.add_field(name="Majority votes", value=f"{s['majority']} ({rate}%)", inline=True)
        embed.add_field(name="Current streak", value=f"🔥 {s['streak']}" if s["streak"] >= 2 else str(s["streak"]), inline=True)
        embed.add_field(name="Best streak", value=str(s["best_streak"]), inline=True)
        await ctx.respond(embed=embed)

    @discord.slash_command(name="eatyeet_suggest", description="Suggest a food for future Eat It or Yeet It rounds!", guild_ids=GUILD_IDS)
    @extra_help("Suggest a food to add to the community pool. Suggested foods can show up in future rounds, credited to you.")
    async def eatyeet_suggest(
        self,
        ctx: discord.ApplicationContext,
        food: discord.Option(str, "The food to suggest (3-100 characters)", required=True),  # type: ignore
    ):
        """Suggest a food for the community pool."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        food = food.strip()
        if not 3 <= len(food) <= 100:
            await ctx.respond("Keep your suggestion between 3 and 100 characters!", ephemeral=True)
            return
        data = load_json(SUGGESTIONS_FILE)
        suggestions = data.setdefault(str(ctx.guild.id), [])
        if any(s["food"].lower() == food.lower() for s in suggestions):
            await ctx.respond("That food was already suggested!", ephemeral=True)
            return
        if len(suggestions) >= MAX_SUGGESTIONS_PER_GUILD:
            await ctx.respond(f"The suggestion pool is full ({MAX_SUGGESTIONS_PER_GUILD} foods)! An admin can clear out old ones.", ephemeral=True)
            return
        suggestions.append({
            "food": food,
            "by": ctx.author.id,
            "by_name": getattr(ctx.author, "display_name", str(ctx.author.id)),
        })
        save_json(SUGGESTIONS_FILE, data)
        await ctx.respond(f"💡 **{food}** added to the community pool! It might show up in a future round.", ephemeral=True)

    @discord.slash_command(name="eatyeet_history", description="Show recent Eat It or Yeet It rounds.", guild_ids=GUILD_IDS)
    @extra_help("Shows the last 10 finished rounds with their foods and verdicts.")
    async def eatyeet_history(self, ctx: discord.ApplicationContext):
        """Show recent rounds."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        stats = load_json(STATS_FILE)
        history = self._guild_stats(stats, ctx.guild.id)["history"]
        if not history:
            await ctx.respond("No finished rounds yet! Start one with /eatyeet.", ephemeral=True)
            return
        lines = []
        for h in reversed(history):
            lines.append(f"{VERDICT_EMOJI.get(h['verdict'], '')} **{h['food']}** — "
                         f"{h['verdict'].upper()} (🍽️{h['eats']} / 🗑️{h['yeets']})")
        embed = discord.Embed(
            title="📜 Eat It or Yeet It — Recent rounds",
            description="\n".join(lines),
            color=0x9B59B6,
        )
        await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(FunCog(bot))
