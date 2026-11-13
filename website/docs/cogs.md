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

Then add `"cogs.my_cog"` to the right list in `bot.py` and restart —
`COGS` if the cog belongs on the main bot, `WORKER_COGS` if it belongs
on the Helper (see below).

## Which bot does a new cog go on?

The codebase runs as **two bots** (same code, `WORKER_MODE` flag):
Havenly Bot 2.0 (main) and Havenly Helper (worker). Decide first,
before writing the cog:

- **Main bot** — real-time user/mod actions: something done *right
  now* for a member or a mod (time someone out, look up a level, run
  a game round). All level commands live here.
- **Helper** — setup/config and batch jobs: configure a channel, scan
  a channel for missing cases, take a backup.

If a cog has commands for both bots, gate each command definition with
a `WORKER_MODE` check at class level (see `cogs/Introduction.py` for
the pattern) — a command only exists on the class in the matching mode,
so it only registers on that bot. Listeners and loops need the same
gating: a listener that ran on both bots would fire twice (that is why
Introduction's listeners and Logger's listener cogs are main-only, and
the board-refresh / tempban-sweep loops are Helper-only).

**Count before you add a top-level command.** Discord caps guild
application commands at 100 per guild. Live counts (Discord API,
2026-11-13): main 54 top-level / 83 runnable, Helper 11 / 30, 0
shared. Plenty of headroom, but count first — and verify the sync
actually registered the command (check the registered command list on
Discord directly), because a bot that restarted healthy can still have
commands that never went live. A sync failure with error 400 code
30032 means the cap was hit: merge the family into a group or remove
a command, then sync again. The Helper only syncs at startup, so a
restart is required for its commands to appear.

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

**Defer ephemeral from the start when the reply must stay private.**
A public defer locks the whole interaction public, and Discord ignores
`ephemeral` on a later followup — so a card sent as ephemeral still
arrives public. (`/add_xp` and `/daily` defer ephemeral for exactly
this reason: their level-up followups must stay private when no level
channel is set.)

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
Gate listeners to the main bot when the work must happen once (see
"Which bot" above).

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
- **`fallback_channel=interaction.channel`** — passed to `award_xp`
  for the level-up announcement path. Note the delivery rule changed
  2026-11-09: if a level channel is set, level-ups post there; if no
  channel is set, a slash-command level-up is an ephemeral followup
  and a message-XP level-up stays silent. **There are no level-up
  DMs** — never send one as a fallback.

## Grantable commands: check in the body, not just the decorator

A decorator like `@admin_required()` only checks the *default* Discord
gate. The custom permission system (`/perm`, Helper-only) lets an admin
grant a command to a specific role or user — and that grant is consulted
by an **in-body** `check_slash_permission` call from
`utils/permissions.py`, not by the decorator. If your command is
grantable, call the check inside the command body (fail-closed: no
grant and no default permission means refuse). Grants live in the
shared `command_permissions` table in Postgres, so they apply to both
bots. See [Permissions](./permissions.md) for the precedence rules.
