# Config & helpers

`config.py` holds the shared constants and helper functions. The important
parts:

- **`GUILD_IDS`** — your test server IDs. The bot warns on boot if it
  hasn't joined every guild listed here (slash sync would 403).
- **`OWNER_IDS`** — your Discord user IDs. Required for `is_owner()`
  commands like `/shutdown_bot`.
- **`statuses`** — the messages `change_status()` rotates through.
- **`load_json(filename)` / `save_json(filename, data)`** — JSON helpers
  (see [Data layer](./data-layer.md)). Missing or corrupt files reset to
  `{}` with a console warning instead of crashing. Note: the six
  migrated names (mod cases, watch list, eatyeet stats/suggestions/
  active/rematch) route through the SQLite store now, not files.
- **`admin_required()` / `is_owner()` / `Manage_*_required()`** —
  permission decorators (see [Permissions](./permissions.md)).
- **`extra_help(text)`** — attaches extended docs to a command.
- **`replace_placeholders(text, member)`** — swaps `{mention}` and
  `{server}` in templates.
- **`COMMAND_TAGS` / `COMMAND_HELP`** — command metadata used by help-ish
  features.
