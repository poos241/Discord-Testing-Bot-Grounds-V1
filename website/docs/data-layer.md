# Data layer

## SQLite (`data/DB/Storage/storage.py`)

One `get_<thing>(guild_id)` / `save_<thing>(guild_id, data)` pair per
table. Tables store one row per guild; complex state lives in a JSON
`data` column. Writes use `OR REPLACE` upserts, so save = insert-or-update.

```python
from data.DB.Storage.storage import get_levels, save_levels

db = await get_levels(str(ctx.guild.id))   # dict, {} if new guild
settings = db.setdefault("settings", {})
settings["xp_min"] = 2
await save_levels(str(ctx.guild.id), db)
```

The levels table is the big one: per-user entries like
`{"xp": 10, "level": 1, "username": "Em", "daily_streak": 3, ...}` plus a
`"settings"` entry holding `xp_min`/`xp_max`, `cooldown`,
`levelup_channel_id`, `level_roles`, `game_xp`, `no_xp_channels`,
`xp_event_until`, `xp_event_multiplier`, and `levelup_message`.

## JSON files (`config.load_json` / `save_json`)

For simple blobs — the game uses these for stats, suggestions, active
rounds, and rematch settings:

```python
from config import load_json, save_json

stats = load_json("eatyeet_stats.json")   # {} if missing/corrupt
stats["123"] = {"points": 5}
save_json("eatyeet_stats.json", stats)
```

Files live in `data/`. Missing or corrupt files reset to `{}` with a
console warning — the bot never crashes on bad JSON.

## Which to use?

- Reaching for per-guild structured data (settings, user records)? **SQLite.**
- Stashing a simple dict the game rewrites often? **JSON file.**
- When in doubt, follow the existing pattern closest to your feature.
