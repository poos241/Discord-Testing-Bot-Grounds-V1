# Developer Guide

This is the **how-it-works** companion to the README. The README tells you
how to *run* the bot; this tells you how the bot is *built* — the
architecture, the patterns each system uses, and copy-paste examples for
adding your own features. If something here disagrees with the code, the
code wins — update this doc when you change the architecture.

## Project map

```
Discord Bot Templet Mde With Python/   <- project root (work from here)
├── bot.py                  # Entry point: token, intents, cog loading, boot
├── config.py               # IDs, permission decorators, JSON helpers, misc data
├── setup.py                # One-shot setup: deps, imports, .env, syntax check
├── requirements.txt        # Python dependencies (single source of truth)
├── .env                    # Your bot token (you create this — never commit it)
├── .env.example            # Template for .env
├── DEVELOPER.md            # This file
├── cogs/
│   ├── admin_cog.py        # Admin slash commands
│   ├── fun_cog.py          # Eat It or Yeet It party game
│   └── Level_system.py     # XP, levels, rank cards, daily, events
├── data/
│   ├── eatyeet_*.json      # Game data: stats, suggestions, active rounds, rematch
│   └── DB/
│       ├── db.py           # Database connection (SQLite)
│       ├── models.py       # Table definitions
│       └── Storage/
│           └── storage.py  # Async get_/save_ helpers, one pair per table
└── utils/
    └── data_utils.py       # Simple JSON load/save helpers
```

Two kinds of persistence exist — pick the right one:

| | SQLite (`storage.py`) | JSON files (`config.load_json`) |
|---|---|---|
| Used by | Levels/XP, cooldown timestamps | Eat It or Yeet It (stats, suggestions, active rounds) |
| Shape | One row per guild, `data` column holds a JSON dict | One file per dataset, plain dicts |
| When to use | Structured data you query per guild | Simple blobs, or data the game writes constantly |

## Boot sequence (`bot.py`)

1. `load_dotenv()` reads `.env`; `TOKEN2` must be set or boot raises.
2. Intents: `members` and `voice_states` are privileged — they must also be
   enabled in the Developer Portal.
3. `commands.Bot` is created and every entry in `COGS` is loaded with
   `load_extension()`. **To add a cog, add its dotted path here.**
4. `on_ready` runs: warns about guilds in `GUILD_IDS` the bot hasn't joined
   (slash sync would 403), then `sync_commands(force=True)`.
5. A background task starts `change_status()`, which rotates the bot's
   presence every 10–60 seconds.

> **Gotcha:** pycord `View` objects need a running event loop at creation,
> but cogs load *before* the loop starts. That's why `fun_cog` defers
> creating its persistent views until `on_ready` (`_ensure_view()`).
> If you add buttons/views, do the same — never build a `View` at import
> or cog `__init__` time. There's a regression test for this
> (`test_noloop.py`).

## Cogs

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

### Slash command patterns

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

## Permissions (`config.py`)

Decorators wrap commands with permission checks. They reply ephemerally
and return `False` when the check fails:

```python
from config import admin_required, is_owner

@commands.slash_command(name="secret", description="Admins only")
@admin_required()
async def secret(self, ctx):
    ...

@commands.slash_command(name="kill", description="Owner only")
@is_owner()
async def kill(self, ctx):
    ...
```

Available: `admin_required()`, `is_owner()`,
`Manage_messages_required()`, `Manage_channels_required()`.
`OWNER_IDS` in `config.py` controls `is_owner()`.

`extra_help(text)` attaches a longer description to a command for
documentation purposes:

```python
@extra_help("Starts a server-wide XP multiplier event (2-5x, up to 24h).")
```

## Data layer

### SQLite (`data/DB/Storage/storage.py`)

One `get_<thing>(guild_id)` / `save_<thing>(guild_id, data)` pair per
table. Tables store one row per guild; complex state lives in a JSON
`data` column. Writes use `OR REPLACE` upserts.

```python
from data.DB.Storage.storage import get_levels, save_levels

db = await get_levels(str(ctx.guild.id))   # dict, {} if new guild
settings = db.setdefault("settings", {})
settings["xp_min"] = 2
await save_levels(str(ctx.guild.id), db)
```

The levels table is the big one: per-user entries
`{"xp": int, "level": int, "username": str, ...}` plus a `"settings"`
entry holding `xp_min/xp_max`, `cooldown`, `levelup_channel_id`,
`level_roles`, `game_xp`, `no_xp_channels`, `xp_event_until`,
`xp_event_multiplier`, `levelup_message`.

### JSON files (`config.load_json` / `save_json`)

```python
from config import load_json, save_json

stats = load_json("eatyeet_stats.json")   # {} if missing/corrupt
stats["123"] = {"points": 5}
save_json("eatyeet_stats.json", stats)
```

Files live in `data/`. Missing or corrupt files reset to `{}` with a
console warning — the bot never crashes on bad JSON.

## Level system internals (`cogs/Level_system.py`)

**Earning XP:** `on_message` rolls `random.randint(xp_min, xp_max)` per
message, subject to the per-user cooldown and the `no_xp_channels` list.

**`award_xp()`** is the single funnel for *all* XP (messages, `/add_xp`,
`/daily`, game votes). It:

1. Applies the active XP event multiplier (unless `apply_event=False`,
   which is how manual `/add_xp` grants stay exact).
2. Adds XP and loops `while xp >= level * 100`, rolling leftovers over.
3. Grants cumulative role rewards (`apply_level_rewards`).
4. Posts the level-up announcement (`announce_level_up`).

**Level-up announcements** go to the configured channel, or fall back to
the channel where the XP was earned. The text is the custom template if
set (`/set_levelup_message`, with `{user}`/`{name}`/`{level}`), otherwise
the default. A confetti card image is attached when Pillow is installed;
without Pillow it's text-only. Nothing crashes either way.

**Cards** (`build_rank_card`, `build_levelup_card`) are pure functions —
give them avatar bytes and stats, get a PNG `BytesIO` back. Avatar
download failures fall back to a solid accent circle, so cards always
render. `/cardcolor` stores a per-user hex accent used by both cards.

**Game XP hook:** `fun_cog` calls the shared `award_level_xp()` after
each round (10 XP per vote + 10 × majority points), honoring the
per-server `game_xp` toggle and XP events.

## Eat It or Yeet It internals (`cogs/fun_cog.py`)

**Round lifecycle:** `/eatyeet` → `_make_round()` picks food + duration →
posts the round embed with vote buttons → countdown task ticks the
message (progress bar, 🔨 HAMMER TIME! under 15s) → expiry tallies votes,
posts results, awards game XP, attaches the 🔁 rematch button.

**Restart safety:** views use `timeout=None` and stable `custom_id`s, and
are re-registered in `on_ready`. Active rounds persist in
`eatyeet_active.json`; an expiry loop tallies anything that ended while
the bot was down. Rematch settings persist per channel in
`eatyeet_rematch.json`.

**Food sources:** Auto (45% TheMealDB API with photo + 🌐 fresh rarity,
else local list), Local only, API only (no round if the API is down —
explicit warning, never silent fallback).

**Scoring:** majority voters earn points by rarity (common 1, weird/fresh/
community 2, cursed 3); streaks and best streaks tracked per user.

## Common recipes

**Per-user cooldown** (dict of timestamps, like `/level`):

```python
now = time.time()
if now - self.cooldowns.get(uid, 0) < 30:
    return await ctx.respond("Slow down!", ephemeral=True)
self.cooldowns[uid] = now
```

**A member who left** — `guild.get_member()` returns `None`; fall back to
a stored username instead of crashing:

```python
member = ctx.guild.get_member(int(uid))
name = member.display_name if member else data.get("username", f"User ID {uid}")
```

**Safe int parsing** for IDs stored as strings:

```python
try:
    channel = guild.get_channel(int(channel_id))
except (ValueError, TypeError):
    channel = None
```

## Testing

Headless tests live next to the code (`test_*.py`). They mock the storage
layer and Discord objects, so they run with no token and no network:

```bash
python test_levels.py    # level system
python test_levels2.py   # no-XP channels, XP events, daily, rank card
python test_levels3.py   # level-up card, card colors, custom messages
python test_gamexp.py    # Eat It or Yeet It -> level XP hook
python test_rematch.py   # rematch button
```

When you add a feature, add a test file (or extend one) following the
existing fake-object pattern, and run the whole suite before pushing.

## Checklist for new features

1. Implement in the cog; add tests; run the full suite.
2. `pip freeze` any new dependency into `requirements.txt`
   (`setup.py` picks it up automatically).
3. Update the **README** command tables (standing rule).
4. Update this doc if the architecture or patterns changed.
5. Push files **one at a time** and verify each by comparing the
   GitHub file **size** to local — never "verify" by decoding content.
6. Tell the user the exact local steps: which files to update, whether
   to `pip install`, restart.
