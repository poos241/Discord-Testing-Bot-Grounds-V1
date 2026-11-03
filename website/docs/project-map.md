# Project map

```
Discord Bot Templet Mde With Python/   <- project root (work from here)
├── bot.py                  # Entry point: token, intents, cog loading, boot, bridge API start
├── bridge_api.py           # Bot-side bridge API (127.0.0.1:5001) the standalone website talks to
├── run_web.py              # Standalone website entry point (python run_web.py)
├── watchdog.py             # Auto-restart watchdog for the bot and the website (exit 1/42 relaunch, 0 stops)
├── run_bot.bat             # Double-click to start the bot under its watchdog
├── run_web.bat             # Double-click to start the website under its watchdog
├── config.py               # IDs, permission decorators, JSON helpers, misc data
├── setup.py                # One-shot setup: deps, imports, .env, syntax check
├── requirements.txt        # Python dependencies (single source of truth)
├── .env                    # Your bot token + BRIDGE_SECRET (you create this — never commit it)
├── .env.example            # Template for .env
├── DEVELOPER.md            # Pointer to this handbook
├── cogs/
│   ├── admin_cog.py        # Admin slash commands (incl. /timeout, /timeout_board, tempban sweep)
│   ├── fun_cog.py          # Eat It or Yeet It party game
│   ├── Level_system.py     # XP, levels, rank cards, daily, events
│   ├── WatchList.py        # User watch list for mods (fail-closed load/save)
│   ├── DebugCog.py         # /debug toggle + logging
│   ├── Logger/             # Event logging (29 event keys)
│   ├── QOTD.py             # Question of the Day
│   ├── Tickets.py          # Support tickets
│   ├── Backup.py           # Backup + restore
│   ├── Appeals.py          # Appeals + mod notes search
│   ├── VoiceXP.py          # Voice time XP
│   ├── Lockdown.py         # Lockdown + slowmode
│   ├── Automod.py          # Automod rules
│   ├── AutoThreads.py      # Auto-threads
│   ├── TimeCmd.py          # /time from profile timezones
│   ├── CustomBadges.py     # Mod-awardable custom badges
│   ├── GHLog.py            # GitHub ban log (Projects board)
│   ├── Introduction.py     # Introduction tracking (channel scan + auto-role)
│   └── Modlogs.py          # Modlog viewer + edit (reads the mod_data behind /userinfo)
├── web/                    # Flask dashboard (port 5000, SEPARATE process — see boot-sequence.md)
│   ├── app.py              # App factory + blueprint registration
│   ├── serve.py            # Waitress server + host/port resolution
│   ├── blueprints/         # One file per page/API area (incl. profiles, backups, directory, feed, friends, voice)
│   ├── templates/          # Jinja pages
│   ├── static/             # CSS/JS + user background uploads (never committed)
│   ├── services/           # Bridge client (bridge.py), local async loop (local_loop.py), permissions, Discord state
│   └── security/           # Login/permission decorators
├── data/
│   ├── eatyeet_*.json      # Legacy JSON, kept as rollback (live data is SQLite now)
│   ├── mod_data.json       # Legacy JSON, kept as rollback (live data is SQLite now)
│   ├── watchlist_data.json # Legacy JSON, kept as rollback (live data is SQLite now)
│   ├── message_log.db      # Logger event log
│   ├── notification_read.json # Bell read state
│   ├── profiles.json.migrated # Pre-SQLite profiles backup
│   └── DB/
│       ├── db.py           # Database connection (SQLite) + column migration
│       ├── models.py       # Table definitions
│       └── Storage/
│           └── storage.py  # Async get_/save_ helpers, one pair per table
├── bot.db                  # Live SQLite database (bot folder root, not data/)
└── utils/
    ├── data_utils.py       # Simple JSON load/save helpers
    ├── backup.py           # Snapshot/restore engine
    ├── github_projects.py  # GitHub Projects v2 API client (GraphQL)
    └── json_sqlite_store.py # Lazy JSON→SQLite store
```

## Picking persistence

Two kinds of persistence exist — pick the right one:

| | SQLite (`storage.py`) | JSON files (`config.load_json`) |
|---|---|---|
| Used by | Levels/XP, cooldown timestamps, user profiles, mod cases, watch list, eatyeet data (migrated Oct 2026), introduction tracking, timeout board config, GitHub ban-log items (Nov 2026) | Notification read state (legacy JSON backups kept as rollback) |
| Shape | One row per guild, `data` column holds a JSON dict | One file per dataset, plain dicts |
| When to use | Structured data you query per guild | Simple blobs, or data the game writes constantly |

See [Data layer](./data-layer.md) for examples of both.

New systems from the October 2026 building-mode batch are documented in [Building-mode batch](./building-mode-batch.md).

## Bot + website: two processes (November 2026)

The bot and the website no longer share a process. The bot runs
`bot.py` (plus the bridge API on `127.0.0.1:5001`); the website runs
`run_web.py` as its own process (port 5000) and reaches live Discord
data only through the bridge (`web/services/bridge.py`), with pure
database reads on its own async loop (`web/services/local_loop.py`).
Each side has its own watchdog (`watchdog.py`, launched by
`run_bot.bat` / `run_web.bat`). See [Boot sequence](./boot-sequence.md)
for the startup order and the bridge secret.
