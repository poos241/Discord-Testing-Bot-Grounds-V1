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

## User profiles (`profiles` + `profile_activity` tables)

Unlike the per-guild tables, profiles are one row per *user*, with real
scalar columns instead of a JSON blob: bio, accent, banner, status,
avatar_url, background_url, pronouns, display_name, featured_badge,
featured_stat, socials/tags (JSON), public, show_roles, roles_guild_id,
roles_position, timezone, location, country, show_local_info, dm_status.
The activity feed is a separate `profile_activity` table (one row per
event: user_id, guild_id, kind, detail JSON, ts unix epoch).

```python
from data.DB.Storage.storage import get_profile, save_profile, log_activity

profile = await get_profile("123")   # canonical dict, defaults if new
profile["bio"] = "Hello!"
await save_profile("123", profile)
await log_activity("123", guild_id, "level_up", {"level": 6})
```

The web dashboard reads profiles through `web/blueprints/profiles.py`:
`GET/POST /api/profile` (login + CSRF), `GET /api/profile/stats`
(login), `GET /api/profile/public/<user-id>` (public), and
`GET /api/profile/roles?guild_id=` (login, membership-checked). Privacy
rules live in that blueprint: public profiles never expose the server
list, the picked guild id is stripped unless roles are opted in, and
timezone/location/country are stripped unless local info is opted in.

## Adding a column to an existing table

`metadata.create_all()` only creates *missing* tables — it never adds a
column to a table that already exists in `bot.db`. If you add a profile
field, you must do both: add the column to the table in `models.py`,
and add it to `_PROFILE_COLUMNS` in `data/DB/db.py`, which runs
`ALTER TABLE ... ADD COLUMN` for any missing columns on boot so
existing databases heal themselves. Forgetting the second half is how
saves start failing with "Unconsumed column names".

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
