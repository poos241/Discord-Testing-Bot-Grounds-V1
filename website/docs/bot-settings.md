# Bot settings overview

Source: `cogs/ServerSettings.py`.

`/bot_settings` (Administrator, guild-scoped, grantable) shows every
bot system's on/off state and key config in one place, so an admin
doesn't have to hunt through each system's own command. It reads the
live config for this server and presents it as a set of embeds.

## What's shown

| Section | What it reads |
|---|---|
| Levels & XP | `levels_enabled`, XP rate, cooldown, level channel, game XP, no-XP channel count, level roles, XP event, level-up message |
| Voice XP | `enabled`, XP/min, daily cap |
| Automod | Which filters are on (spam, invites, external links, caps), spam threshold/window |
| Logger | Log channels set (per category) and how many of the 29 events are on |
| Lockdown | Channels the bot currently has locked |
| WatchList | Watched user count, log channel |
| Tickets | On/off, panel channel, open ticket count, next ticket number |
| QOTD | On/off, channel |
| Debug | On/off (global, not per-server) |
| Introductions | Intro channel, role, log channel, auto-assign/scan toggles |
| Appeals | On/off |
| Ban log | Evidence channel |
| Timeout board | Board channel |
| Badges | Custom badge count + names |

## Design notes

- **One section, one store.** Each section reads its own storage
  (the async `data/DB/Storage/storage.py` helpers, the Logger's own
  SQLite DB, the watchlist store, or the debug flag file) and is
  wrapped so one unreadable system shows "couldn't read" instead of
  breaking the whole overview. Sections run concurrently with
  `asyncio.gather(..., return_exceptions=True)`.
- **Blocking reads stay off the event loop.** The Logger (sync
  `sqlite3`) and the watchlist store (sync) are read via
  `asyncio.to_thread`.
- **Custom permissions are intentionally left out.** They have their
  own `/perm_overview` and `/perm_commands`; the overview's footer
  points there.
- **One embed per message.** Discord caps the total characters across
  all embeds in one message at 6000, not 6000 per embed, so the
  overview chunks fields (splitting on line boundaries, never
  mid-line) and sends one embed per followup message.
- **Pycord gotcha.** A command method may not start with `bot_` or
  `cog_` — the method is `show_bot_settings`, while the command name
  stays `bot_settings`.
