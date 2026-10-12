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
