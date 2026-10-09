# cogs/fun_cog.py
"""Fun party games for the server. First game: Eat It or Yeet It."""
import random
import time

import discord
from discord.ext import commands

from config import load_json, save_json, extra_help, GUILD_IDS

STATS_FILE = "eatyeet_stats.json"
SUGGESTIONS_FILE = "eatyeet_suggestions.json"
ROUND_SECONDS = 30
START_COOLDOWN = 30  # seconds before the same user can start another round
MAX_SUGGESTIONS_PER_GUILD = 25
SUGGESTION_CHANCE = 0.25  # chance a round pulls a community-suggested food

RARITY_EMOJI = {"common": "🟢", "weird": "🟡", "cursed": "🟣", "community": "💡"}
RARITY_POINTS = {"common": 1, "weird": 2, "cursed": 3, "community": 2}

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
    """The voting buttons for one round of Eat It or Yeet It."""

    def __init__(self, cog, food_name, rarity, guild_id, channel_id, starter_id, suggested_by=None):
        super().__init__(timeout=ROUND_SECONDS)
        self.cog = cog
        self.food_name = food_name
        self.rarity = rarity
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.starter_id = starter_id
        self.suggested_by = suggested_by  # display name of suggester, or None
        self.votes = {}  # user_id -> "eat" | "yeet"
        self.voter_names = {}  # user_id -> display name
        self.verdict = None  # "eat" | "yeet" | "tie" | "none"
        self.streak_shoutouts = []  # [(name, streak), ...] filled in at finish
        self.message = None
        self._ended = False
        self._last_edit = 0.0

    async def _register_vote(self, interaction: discord.Interaction, choice: str):
        self.votes[interaction.user.id] = choice
        self.voter_names[interaction.user.id] = getattr(interaction.user, "display_name", "Someone")
        word = "EAT IT 🍽️" if choice == "eat" else "YEET IT 🗑️"
        await interaction.response.send_message(
            f"You voted **{word}** for {self.food_name}!",
            ephemeral=True,
        )
        await self._refresh_counts()

    @discord.ui.button(label="Eat it!", emoji="🍽️", style=discord.ButtonStyle.success)
    async def eat_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._register_vote(interaction, "eat")

    @discord.ui.button(label="Yeet it!", emoji="🗑️", style=discord.ButtonStyle.danger)
    async def yeet_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self._register_vote(interaction, "yeet")

    def counts(self):
        eats = sum(1 for v in self.votes.values() if v == "eat")
        yeets = sum(1 for v in self.votes.values() if v == "yeet")
        return eats, yeets

    async def _refresh_counts(self):
        # Throttled live update of the vote counts (avoids rate limits).
        if self.message is None or self._ended:
            return
        now = time.time()
        if now - self._last_edit < 2:
            return
        self._last_edit = now
        try:
            await self.message.edit(embed=self.cog.build_round_embed(self))
        except discord.HTTPException:
            pass

    async def _finish(self):
        if self._ended:
            return
        self._ended = True
        for child in self.children:
            child.disabled = True
        self.cog.finish_round(self)
        if self.message is not None:
            try:
                await self.message.edit(embed=self.cog.build_results_embed(self), view=self)
            except discord.HTTPException:
                pass

    async def on_timeout(self):
        await self._finish()

    async def end_early(self):
        """End the round before the timer runs out (starter/admin only)."""
        self.stop()  # cancel the timeout timer
        await self._finish()


class FunCog(commands.Cog):
    """Party games for the server."""

    def __init__(self, bot):
        self.bot = bot
        self.active_rounds = {}  # channel_id -> EatYeetView
        self.start_cooldowns = {}  # user_id -> timestamp of last round started

    # ----- helpers -----

    def _guild_stats(self, stats, guild_id):
        """Get (creating if needed) a guild's stats block, migrating old keys.

        Old v1 files used "voted"; they are migrated to "played" (plus new
        defaults) and written back so the migration only happens once."""
        g = stats.setdefault(str(guild_id), {"rounds": 0, "users": {}})
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
        if migrated:
            save_json(STATS_FILE, stats)
        return g

    def _get_suggestions(self, guild_id):
        data = load_json(SUGGESTIONS_FILE)
        return data.get(str(guild_id), [])

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

    def build_round_embed(self, view: EatYeetView) -> discord.Embed:
        eats, yeets = view.counts()
        points = RARITY_POINTS[view.rarity]
        desc = f"**{view.food_name}**\n{RARITY_EMOJI[view.rarity]} Rarity: **{view.rarity.title()}**"
        if view.suggested_by:
            desc += f"\n💡 Suggested by **{view.suggested_by}**"
        embed = discord.Embed(
            title="🍽️ EAT IT or YEET IT 🗑️",
            description=desc,
            color=0x9B59B6,
        )
        embed.add_field(name="🍽️ Eat it", value=f"**{eats}**", inline=True)
        embed.add_field(name="🗑️ Yeet it", value=f"**{yeets}**", inline=True)
        embed.set_footer(text=f"Vote with the buttons below! You can change your vote. "
                              f"Majority voters earn {points} pt{'s' if points != 1 else ''}. Voting ends in {ROUND_SECONDS}s.")
        return embed

    def build_results_embed(self, view: EatYeetView) -> discord.Embed:
        eats, yeets = view.counts()
        score = f"🍽️ **{eats}** — 🗑️ **{yeets}**"
        if view.verdict == "eat":
            title, color = "😋 EATEN!", 0x2ECC71
            desc = f"**{view.food_name}**\n{score}\n\n_{random.choice(EAT_WINS)}_"
        elif view.verdict == "yeet":
            title, color = "🗑️ YEETED!", 0xE74C3C
            desc = f"**{view.food_name}**\n{score}\n\n_{random.choice(YEET_WINS)}_"
        elif view.verdict == "tie":
            title, color = "✨ IT'S A TIE!", 0xF1C40F
            desc = f"**{view.food_name}**\n{score}\n\n_{random.choice(TIES)}_"
        else:
            title, color = "😐 Nobody voted", 0x95A5A6
            desc = f"**{view.food_name}**\n\n_{NO_VOTES}_"
        if view.streak_shoutouts:
            desc += "\n\n" + "\n".join(f"🔥 **{name}** is on a {streak}-round streak!"
                                       for name, streak in view.streak_shoutouts)
        return discord.Embed(title=title, description=desc, color=color)

    def finish_round(self, view: EatYeetView):
        """Tally the verdict, award points/streaks, save stats, free the channel."""
        self.active_rounds.pop(view.channel_id, None)
        eats, yeets = view.counts()
        if eats == 0 and yeets == 0:
            view.verdict = "none"
        elif eats > yeets:
            view.verdict = "eat"
        elif yeets > eats:
            view.verdict = "yeet"
        else:
            view.verdict = "tie"

        majority_voters = set()
        if view.verdict in ("eat", "yeet"):
            majority_voters = {uid for uid, vote in view.votes.items() if vote == view.verdict}

        stats = load_json(STATS_FILE)
        guild_stats = self._guild_stats(stats, view.guild_id)
        guild_stats["rounds"] += 1
        for user_id, vote in view.votes.items():
            u = guild_stats["users"].setdefault(str(user_id), {
                "played": 0, "points": 0, "majority": 0, "streak": 0, "best_streak": 0,
            })
            u["played"] += 1
            if user_id in majority_voters:
                u["majority"] += 1
                u["points"] += RARITY_POINTS[view.rarity]
                u["streak"] += 1
                u["best_streak"] = max(u["best_streak"], u["streak"])
            else:
                u["streak"] = 0
        save_json(STATS_FILE, stats)

        # Streak shoutouts for the results embed (3+ round streaks only).
        shoutouts = []
        for uid in majority_voters:
            u = guild_stats["users"][str(uid)]
            if u["streak"] >= 3:
                shoutouts.append((view.voter_names.get(uid, "Someone"), u["streak"]))
        shoutouts.sort(key=lambda x: x[1], reverse=True)
        view.streak_shoutouts = shoutouts[:3]

    # ----- commands -----

    @discord.slash_command(name="eatyeet", description="Start a round of Eat It or Yeet It!", guild_ids=GUILD_IDS)
    @extra_help("Starts a round of Eat It or Yeet It. The bot serves up a random food and everyone votes with the buttons. After 30 seconds the verdict is announced, points and streaks are saved.")
    async def eatyeet(self, ctx: discord.ApplicationContext):
        """Start a round of Eat It or Yeet It."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        if ctx.channel.id in self.active_rounds:
            await ctx.respond("There's already a round going in this channel — vote on that one first!", ephemeral=True)
            return
        now = time.time()
        last = self.start_cooldowns.get(ctx.author.id, 0)
        if now - last < START_COOLDOWN:
            wait = int(START_COOLDOWN - (now - last))
            await ctx.respond(f"Slow down! You can start another round in {wait} seconds.", ephemeral=True)
            return
        self.start_cooldowns[ctx.author.id] = now

        food, rarity, suggested_by = self._pick_food(ctx.guild.id)
        view = EatYeetView(self, food, rarity, ctx.guild.id, ctx.channel.id,
                           starter_id=ctx.author.id, suggested_by=suggested_by)
        self.active_rounds[ctx.channel.id] = view

        await ctx.respond(embed=self.build_round_embed(view), view=view)
        view.message = await ctx.interaction.original_response()

    @discord.slash_command(name="eatyeet_end", description="End the current Eat It or Yeet It round early.", guild_ids=GUILD_IDS)
    @extra_help("Ends the active Eat It or Yeet It round in this channel right away. Only the person who started it (or an admin) can use this.")
    async def eatyeet_end(self, ctx: discord.ApplicationContext):
        """End the active round in this channel early."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        view = self.active_rounds.get(ctx.channel.id)
        if view is None:
            await ctx.respond("There's no active round in this channel.", ephemeral=True)
            return
        is_starter = ctx.author.id == view.starter_id
        is_admin = ctx.author.guild_permissions.administrator
        if not (is_starter or is_admin):
            await ctx.respond("Only the person who started the round (or an admin) can end it early.", ephemeral=True)
            return
        await ctx.respond("Ending the round early! Tallying the votes...", ephemeral=True)
        await view.end_early()

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


def setup(bot):
    bot.add_cog(FunCog(bot))
