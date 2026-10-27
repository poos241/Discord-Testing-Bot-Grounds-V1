# Project map

```
Discord Bot Templet Mde With Python/   <- project root (work from here)
├── bot.py                  # Entry point: token, intents, cog loading, boot
├── config.py               # IDs, permission decorators, JSON helpers, misc data
├── setup.py                # One-shot setup: deps, imports, .env, syntax check
├── requirements.txt        # Python dependencies (single source of truth)
├── .env                    # Your bot token (you create this — never commit it)
├── .env.example            # Template for .env
├── DEVELOPER.md            # Pointer to this handbook
├── cogs/
│   ├── admin_cog.py        # Admin slash commands
│   ├── fun_cog.py          # Eat It or Yeet It party game
│   ├── Level_system.py     # XP, levels, rank cards, daily, events
│   ├── WatchList.py        # User watch list for mods
│   ├── DebugCog.py         # /debug toggle + logging
│   └── Logger/             # Event logging (29 event keys)
├── web/                    # Flask dashboard (port 5000)
│   ├── app.py              # App factory + blueprint registration
│   ├── blueprints/         # One file per page/API area (incl. profiles)
│   ├── templates/          # Jinja pages
│   ├── static/             # CSS/JS + user background uploads (never committed)
│   ├── services/           # Discord state, permissions
│   └── security/           # Login/permission decorators
├── data/
│   ├── eatyeet_*.json      # Game data: stats, suggestions, active rounds, rematch
│   ├── mod_data.json       # Warns/notes/cases (admin cog)
│   ├── watchlist_data.json # Watch list
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
    └── data_utils.py       # Simple JSON load/save helpers
```

## Picking persistence

Two kinds of persistence exist — pick the right one:

| | SQLite (`storage.py`) | JSON files (`config.load_json`) |
|---|---|---|
| Used by | Levels/XP, cooldown timestamps, user profiles | Eat It or Yeet It (stats, suggestions, active rounds), mod cases, watch list, notification read state |
| Shape | One row per guild, `data` column holds a JSON dict | One file per dataset, plain dicts |
| When to use | Structured data you query per guild | Simple blobs, or data the game writes constantly |

See [Data layer](./data-layer.md) for examples of both.
