# Project map

```
Discord Bot Templet Mde With Python/   <- project root (work from here)
├── bot.py                  # Entry point: token, intents, cog loading, boot, bridge API start
│                           # WORKER_MODE env var picks main bot vs Havenly Helper (WORKER_COGS)
├── bridge_api.py           # Bot-side bridge API the website talks to:
│                           #   main bridge 127.0.0.1:5001 (full API) / worker hub 127.0.0.1:5002 (status + jobs)
├── run_web.py              # Standalone website entry point (python run_web.py)
├── watchdog.py             # Auto-restart watchdog for the bot and the website (exit 1/42 relaunch, 0 stops)
├── run_bot.bat             # Double-click to start the bot under its watchdog
├── run_web.bat             # Double-click to start the website under its watchdog
├── config.py               # IDs, permission decorators, JSON helpers, misc data (WORKER_MODE flag lives here)
├── setup.py                # One-shot setup: deps, imports, .env, syntax check
├── requirements.txt        # Python dependencies (single source of truth)
├── .env                    # Tokens + DATABASE_URL + BRIDGE_SECRET (you create this — never commit it)
├── .env.example            # Template for .env
├── DEVELOPER.md            # Pointer to this handbook
├── cogs/
│   ├── admin_cog.py        # Admin slash commands (incl. /timeout, tempban sweep, timeout-board refresh)
│   ├── fun_cog.py          # Eat It or Yeet It party game
│   ├── Level_system.py     # XP, levels, rank cards, daily, events (main bot only)
│   ├── WatchList.py        # User watch list for mods (fail-closed load/save)
│   ├── DebugCog.py         # /debug toggle + logging
│   ├── Logger/             # Event logging (29 event keys; listeners main-only, commands on the Helper)
│   ├── QOTD.py             # Question of the Day (posting main-only, config on the Helper)
│   ├── Backup.py           # Backup + restore (Helper only)
│   ├── Lockdown.py         # Lockdown + slowmode
│   ├── GHLog.py            # GitHub ban log (Projects board)
│   ├── Introduction.py     # Introduction tracking (listeners main-only, setup/scan on the Helper)
│   ├── Modlogs.py          # Modlog viewer + edit (reads the mod_data behind /userinfo)
│   ├── Permissions.py      # Custom per-command permissions (Helper only)
│   ├── ServerSettings.py   # /bot_settings (Helper only)
│   ├── Help_Info_Doc.py    # /help and the docs commands
│   ├── KumaHeartbeat.py    # Uptime Kuma push heartbeat (both bots, different push URLs)
│   ├── Tickets.py          # DISABLED — support tickets (deliberately off, 2026-11-12)
│   ├── Appeals.py          # DISABLED — appeals + mod notes search (deliberately off, 2026-11-12)
│   ├── VoiceXP.py          # DISABLED — voice time XP (deliberately off, 2026-11-12)
│   ├── Automod.py          # DISABLED — automod rules (deliberately off, 2026-11-12)
│   ├── AutoThreads.py      # DISABLED — auto-threads (deliberately off, 2026-11-12)
│   ├── TimeCmd.py          # DISABLED — /time from profile timezones (deliberately off, 2026-11-12)
│   └── CustomBadges.py     # DISABLED — mod-awardable custom badges (deliberately off, 2026-11-12)
├── web/                    # Flask dashboard (port 5000, SEPARATE process — see boot-sequence.md)
│   ├── app.py              # App factory + blueprint registration
│   ├── serve.py            # Waitress server + host/port resolution
│   ├── blueprints/         # One file per page/API area (incl. profiles, backups, directory, feed, friends, voice)
│   ├── templates/          # Jinja pages
│   ├── static/             # CSS/JS + user background uploads (never committed)
│   ├── services/           # Bridge client (bridge.py), local async loop (local_loop.py), permissions, Discord state
│   └── security/           # Login/permission decorators
├── data/
│   ├── eatyeet_*.json      # Legacy JSON, kept as rollback (live data is Postgres now)
│   ├── mod_data.json       # Legacy JSON, kept as rollback (live data is Postgres now)
│   ├── watchlist_data.json # Legacy JSON, kept as rollback (live data is Postgres now)
│   ├── message_log.db      # FROZEN legacy SQLite copy (2026-11-12) — live data is Postgres now
│   ├── notification_read.json # Bell read state
│   ├── profiles.json.migrated # Pre-SQLite profiles backup
│   └── DB/
│       ├── db.py           # Database connection (Postgres, SerialisedDatabase) + column migration
│       ├── models.py       # Table definitions
│       └── Storage/
│           └── storage.py  # Async get_/save_ helpers, one pair per table (Postgres ON CONFLICT upserts)
├── bot.db                  # FROZEN legacy SQLite copy (2026-11-12 11:41) — live data is Postgres now
└── utils/
    ├── data_utils.py       # Simple JSON load/save helpers
    ├── backup.py           # Snapshot/restore engine (pg_dump based)
    ├── github_projects.py  # GitHub Projects v2 API client (GraphQL)
    └── json_sqlite_store.py # Lazy JSON→Postgres store (name kept so imports work; psycopg now)
```

> **The seven disabled cogs are intentional.** VoiceXP, Tickets,
> Appeals, Automod, AutoThreads, TimeCmd, and CustomBadges are
> commented out in `bot.py` and their commands are **not registered**
> on either bot (disabled 2026-11-12). Do not uncomment them, and do
> not list their commands as active anywhere. Their files stay in
> `cogs/` for reference. `/auto_thread` does not exist for the same
> reason.

## Postgres (repo root)

The database lives outside the bot folder, in `servers/postgres/` at
the repo root: `docker-compose.yml` (Postgres 17 container
`havenly-postgres`) plus `.env.postgres` (database password, never
committed). Data persists in the named Docker volume
`havenly_pgdata`. The bot reaches it through `DATABASE_URL` in the
bot folder's `.env`.

## Picking persistence

Two kinds of persistence exist — pick the right one:

| | Postgres (`storage.py`) | JSON files (`config.load_json`) |
|---|---|---|
| Used by | Levels/XP, cooldown timestamps, user profiles, mod cases, watch list, eatyeet data, introduction tracking, timeout board config, GitHub ban-log items | Notification read state (legacy JSON backups kept as rollback) |
| Shape | One row per guild, `data` column holds a JSONB dict | One file per dataset, plain dicts |
| When to use | Structured data you query per guild | Simple blobs, or data the game writes constantly |

See [Data layer](./data-layer.md) for examples of both.

New systems from the October 2026 building-mode batch are documented in [Building-mode batch](./building-mode-batch.md).

## Bot + website: three processes (November 2026)

The system runs as **three separate processes**, all from the same
codebase:

| Process | What it runs | Bridge |
| --- | --- | --- |
| **Havenly Bot 2.0** (main bot) | `bot.py` — real-time moderation, levels, games, QOTD posting | Main bridge `127.0.0.1:5001` (full API) |
| **Havenly Helper** (worker) | `WORKER_MODE=1 python bot.py` — setup/config, batch jobs, backups, timeout board | Worker hub `127.0.0.1:5002` (status + jobs only) |
| **Website** | `run_web.py` (port 5000) | Talks to both bots through their bridges (`web/services/bridge.py`) |

The main bot and the Helper share one Postgres database (`havenly`)
and never talk via Discord messages — they ask each other to do work
through the bridge hub. The website reaches live Discord data only
through the bridges, with pure database reads on its own async loop
(`web/services/local_loop.py`). Each side has its own watchdog
(`watchdog.py`, launched by `run_bot.bat` / `run_web.bat`) and its own
systemd service (`kushbot`, `havenly-helper`, `kushweb`). See
[Boot sequence](./boot-sequence.md) for the startup order and the
bridge secret.
