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

## JSON files — legacy since October 2026

`config.load_json` / `save_json` still exist, but the six files they used
to own — mod cases, watch list, and Eat It or Yeet It stats, suggestions,
active rounds, and rematch settings — moved to SQLite in October 2026
(see the migration note below). `load_json` / `save_json` route those
names through `utils/json_sqlite_store.py` now, so old call sites keep
working while the data lives in tables. The original JSON files stay on
disk untouched as rollback copies.

The only JSON file still live is the notification bell's read state
(`data/notification_read.json`). Missing or corrupt files reset to `{}`
with a console warning — the bot never crashes on bad JSON.

## The JSON → SQLite migration (October 2026)

`utils/json_sqlite_store.py` maps the six legacy files to seven tables
(`mod_data`, `watchlist_data`, `eatyeet_stats`, `eatyeet_suggestions`,
`eatyeet_active`, `eatyeet_rematch`, plus a `json_migrations` tracker).
Migration is **lazy**: the first load/save after a restart imports the
JSON into SQLite; the originals are never deleted, so rollback is
restoring the pre-migration code plus the JSON backups. New code should
use the store helpers or a new table — not a new JSON file.

### Hardened loads (October 2026)

`load_store` retries locked-database errors like `save_store` already
did, and it no longer falls back to the pre-migration JSON once the store
was migrated: on a persistent read failure it returns the legacy file
only when the store was never migrated, and raises otherwise. A failed
read used to silently roll a live table back to frozen pre-migration
data on the next save; now a truly unreadable database errors visibly
instead. Ticket numbers are claimed under a per-guild `asyncio.Lock`
before the channel is created, so two simultaneous opens can no longer
share a number (a later failure leaves a harmless gap, never a
duplicate).

### Read-only fast path (November 2026)

Every `load_store` used to open a read-write connection and run
`BEGIN IMMEDIATE` + commit — a write lock just to peek at the data.
The timeout board's 1-minute refresh did that on the Discord event
loop while the website thread held the lock, and the loop stalled
long enough for Discord to warn the heartbeat was blocked. Reads of
a migrated store now go through a read-only connection (no write
lock, no commit) and only fall through to the write path when setup
or migration is still needed. The fallback semantics above are
unchanged: a migrated store can never get the stale legacy JSON back.
Board refreshes additionally run their database loads in a
background thread (`asyncio.to_thread`), so a slow read can no
longer freeze the event loop at all.

### WatchList fails closed (November 2026)

The WatchList cog used to swallow any load error and start with an
empty dict — and its save replaces the whole table, so the next watch
add after a failed load would silently overwrite the live
`watchlist_data` table with just the new change. It now tracks a
`_db_ok` flag: a failed load marks the store unusable, every
read-mutate path retries the load first, commands report
"temporarily unavailable — nothing was changed" instead of operating
on empty data, saves refuse while unusable, and save failures log
loudly with a traceback. The store heals itself on the next
successful reload. Cross-process note (split): the bot's WatchList
cog caches its table in memory, so it does not see website-added
watches until the bot restarts — and could overwrite them on its
next bot-side save. A bridge watch endpoint would fix that properly.

### Profile migration failures are loud (November 2026)

The profile-columns migration (`_ensure_profile_columns` in
`data/DB/db.py`) used to swallow an `ALTER TABLE` failure with one
quiet line and boot on a stale schema. It now logs a loud `[DB]
ERROR` with the full traceback and records
`PROFILE_MIGRATION_ERROR`, which `/api/debug/bot-status` surfaces as
`profile_migration_error` (null when healthy). It deliberately does
not raise at import — a profiles-table problem must not kill the
whole bot.

### New tables (November 2026)

- `introduction_status` + `introduction_config` — introduction
  tracking (one row per guild/user; see the README section).
- `timeout_board_config` — timeout board channel + message id per
  guild (the board itself reads the existing `mod_data` timeouts and
  tempbans; there is no separate timeout store).
- `ghlog_items` — GitHub ban-log items tracked locally so updates
  and deletes find the right board item.

## Which to use?

- Anything new, per-guild or per-user, structured or a simple dict?
  **SQLite** — either a new table (see
  [Adding a database table](./adding-a-table.md)) or the store pattern
  for JSON-shaped data.
- The only standing JSON exception is the notification bell's read state.
- When in doubt, follow the existing pattern closest to your feature.
