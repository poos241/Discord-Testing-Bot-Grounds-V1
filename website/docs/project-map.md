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

## Picking persistence

Two kinds of persistence exist — pick the right one:

| | SQLite (`storage.py`) | JSON files (`config.load_json`) |
|---|---|---|
| Used by | Levels/XP, cooldown timestamps | Eat It or Yeet It (stats, suggestions, active rounds) |
| Shape | One row per guild, `data` column holds a JSON dict | One file per dataset, plain dicts |
| When to use | Structured data you query per guild | Simple blobs, or data the game writes constantly |

See [Data layer](./data-layer.md) for examples of both.
