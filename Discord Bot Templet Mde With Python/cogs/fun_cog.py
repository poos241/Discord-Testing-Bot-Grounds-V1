# cogs/fun_cog.py
"""Fun party games for the server. First game: Eat It or Yeet It."""
import random
import time

import discord
from discord.ext import commands

from config import load_json, save_json, extra_help

STATS_FILE = "eatyeet_stats.json"
ROUND_SECONDS = 30
START_COOLDOWN = 30  # seconds before the same user can start another round

RARITY_EMOJI = {"common": "🟢", "weird": "🟡", "cursed": "🟣"}

# (common 50% / weird 35% / cursed 15%)
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
]

YEET_WINS = [
    "YEETED! Straight into the sun. 🗑️☀️",
    "The people have rejected it. Launched into orbit. 🚀",
    "Yeeted with extreme prejudice. Nobody wanted that. 💥",
    "Into the trash dimension it goes. 🌀",
]

TIES = [
    "It's a perfect tie! The food ascends to a higher plane, uneaten and unyeeted. ✨",
    "Dead even! The food is spared... for now. 👀",
]

NO_VOTES = "Nobody voted... the food sits there, judging you all. 😐"


class EatYeetView(discord.ui.View):
    """The voting buttons for one round of Eat It or Yeet It."""

    def __init__(self, cog, food_name, rarity, guild_id, channel_id):
        super().__init__(timeout=ROUND_SECONDS)
        self.cog = cog
        self.food_name = food_name
        self.rarity = rarity
        self.guild_id = guild_id
        self.channel_id = channel_id
        self.votes = {}  # user_id -> "eat" | "yeet"
        self.verdict = None  # "eat" | "yeet" | "tie" | "none"
        self.message = None
        self._ended = False
        self._last_edit = 0.0

    async def _register_vote(self, interaction: discord.Interaction, choice: str):
        self.votes[interaction.user.id] = choice
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

    async def on_timeout(self):
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


class FunCog(commands.Cog):
    """Party games for the server."""

    def __init__(self, bot):
        self.bot = bot
        self.active_rounds = set()  # channel ids with a live round
        self.start_cooldowns = {}  # user_id -> timestamp of last round started

    # ----- helpers -----

    def _pick_food(self):
        roll = random.random()
        if roll < 0.15:
            rarity = "cursed"
        elif roll < 0.50:
            rarity = "weird"
        else:
            rarity = "common"
        return random.choice(FOODS[rarity]), rarity

    def build_round_embed(self, view: EatYeetView) -> discord.Embed:
        eats, yeets = view.counts()
        embed = discord.Embed(
            title="🍽️ EAT IT or YEET IT 🗑️",
            description=f"**{view.food_name}**\n{RARITY_EMOJI[view.rarity]} Rarity: **{view.rarity.title()}**",
            color=0x9B59B6,
        )
        embed.add_field(name="🍽️ Eat it", value=f"**{eats}**", inline=True)
        embed.add_field(name="🗑️ Yeet it", value=f"**{yeets}**", inline=True)
        embed.set_footer(text=f"Vote with the buttons below! You can change your vote. Voting ends in {ROUND_SECONDS}s.")
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
        return discord.Embed(title=title, description=desc, color=color)

    def finish_round(self, view: EatYeetView):
        """Tally the verdict, save stats, and free the channel."""
        self.active_rounds.discard(view.channel_id)
        eats, yeets = view.counts()
        if eats == 0 and yeets == 0:
            view.verdict = "none"
        elif eats > yeets:
            view.verdict = "eat"
        elif yeets > eats:
            view.verdict = "yeet"
        else:
            view.verdict = "tie"

        stats = load_json(STATS_FILE)
        guild_stats = stats.setdefault(str(view.guild_id), {"rounds": 0, "users": {}})
        guild_stats["rounds"] += 1
        for user_id, vote in view.votes.items():
            user_stats = guild_stats["users"].setdefault(str(user_id), {"voted": 0, "majority": 0})
            user_stats["voted"] += 1
            if (view.verdict == "eat" and vote == "eat") or (view.verdict == "yeet" and vote == "yeet"):
                user_stats["majority"] += 1
        save_json(STATS_FILE, stats)

    # ----- commands -----

    @discord.slash_command(name="eatyeet", description="Start a round of Eat It or Yeet It!")
    @extra_help("Starts a round of Eat It or Yeet It. The bot serves up a random food and everyone votes with the buttons. After 30 seconds the verdict is announced and stats are saved.")
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

        food, rarity = self._pick_food()
        view = EatYeetView(self, food, rarity, ctx.guild.id, ctx.channel.id)
        self.active_rounds.add(ctx.channel.id)

        await ctx.respond(embed=self.build_round_embed(view), view=view)
        view.message = await ctx.interaction.original_response()

    @discord.slash_command(name="eatyeet_leaderboard", description="Show the Eat It or Yeet It leaderboard.")
    @extra_help("Shows the top 10 players ranked by how often they voted with the winning side.")
    async def eatyeet_leaderboard(self, ctx: discord.ApplicationContext):
        """Show the Eat It or Yeet It leaderboard."""
        if ctx.guild is None:
            await ctx.respond("This game needs a server to play in — try it in a channel!", ephemeral=True)
            return
        stats = load_json(STATS_FILE)
        users = stats.get(str(ctx.guild.id), {}).get("users", {})
        if not users:
            await ctx.respond("No rounds played yet! Start one with /eatyeet.", ephemeral=True)
            return
        ranked = sorted(users.items(), key=lambda kv: kv[1]["majority"], reverse=True)[:10]
        lines = []
        for i, (user_id, s) in enumerate(ranked, start=1):
            member = ctx.guild.get_member(int(user_id))
            name = member.display_name if member else f"<@{user_id}>"
            lines.append(f"**{i}.** {name} — {s['majority']} majority votes ({s['voted']} rounds)")
        embed = discord.Embed(
            title="🏆 Eat It or Yeet It — Leaderboard",
            description="\n".join(lines),
            color=0xF1C40F,
        )
        await ctx.respond(embed=embed)


def setup(bot):
    bot.add_cog(FunCog(bot))
