# Cogs

A cog is one file in `cogs/` with a class and a `setup()` function.
Minimal example:

```python
import discord
from discord.ext import commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="hello", description="Say hello")
    async def hello(self, ctx: discord.ApplicationContext):
        await ctx.respond("Hello!")

def setup(bot):
    bot.add_cog(MyCog(bot))
```

Then add `"cogs.my_cog"` to `COGS` in `bot.py` and restart.

## Slash command patterns

**Quick reply** (under ~3 seconds of work):

```python
@discord.slash_command(name="ping", description="Ping the bot")
async def ping(self, ctx):
    await ctx.respond("Pong!")
```

**Slow work** (API calls, image generation) — defer first, then followup:

```python
await ctx.response.defer()
# ... do slow stuff ...
await ctx.followup.send("Done!")
```

> **Gotcha:** after `defer()`, you must use `followup.send`, not
> `respond` — calling `respond` raises "interaction already acknowledged".

**Options and ephemeral replies:**

```python
@discord.slash_command(name="echo", description="Echo text privately")
async def echo(self, ctx,
               text: discord.Option(str, "What to say")):
    await ctx.respond(text, ephemeral=True)
```

**Listeners** (non-command events):

```python
@commands.Cog.listener()
async def on_message(self, message: discord.Message):
    if message.author.bot or not message.guild:
        return
    ...
```

Note: `bot.py` also defines a global `on_message` that calls
`client.process_commands(message)` — cog listeners run alongside it.

## Complete example: an admin command with options

This is the shape most real commands take — permission check, an option,
deferred work, and an ephemeral error path:

```python
from config import admin_required, extra_help

class LevelSystem(commands.Cog):
    @commands.slash_command(name="add_xp", description="Add XP to a user")
    @extra_help("Add XP to a user. Admins only. Level-ups are announced like normal.")
    @admin_required()
    async def add_xp(self, interaction, member: discord.Member, amount: int):
        # validate first, reply ephemerally on bad input
        if amount <= 0:
            return await interaction.respond(
                "Amount must be positive.", ephemeral=True)
        # award_xp handles level-ups, role rewards, and announcements
        gained = await award_xp(interaction.guild, member.id,
                                member.display_name, amount,
                                fallback_channel=interaction.channel,
                                apply_event=False)
        if gained:
            await interaction.respond(
                f"✅ Added {amount} XP to {member.mention} — "
                f"they leveled up to **{gained[-1]}**! 🎉")
        else:
            await interaction.respond(
                f"✅ Added {amount} XP to {member.mention}.")

def setup(bot):
    bot.add_cog(LevelSystem(bot))
```

Patterns to notice:

- **Decorators stack**: `@slash_command` → `@extra_help` → `@admin_required`.
  Order matters — the command decorator goes on top.
- **Validate before doing work**, and make error replies `ephemeral` so
  mistakes don't spam the channel.
- **Delegate to shared helpers** (`award_xp`) instead of reimplementing
  level math, rewards, and announcements in every command.
- **`fallback_channel=interaction.channel`** — level-up announcements need
  somewhere to go when no level-up channel is configured.
