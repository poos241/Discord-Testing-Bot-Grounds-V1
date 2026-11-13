# Bot settings overview

Source: `cogs/ServerSettings.py`.

`/bot_settings` (Administrator, guild-scoped, grantable) shows every
bot system's on/off state and key config in one place, so an admin
doesn't have to hunt through each system's own command. It reads the
live config for this server and presents it as a set of embeds. The
command itself runs on **Havenly Helper**; the data it shows comes
from the shared Postgres database both bots use.

## What's shown

| Section | What it reads |
|---|---|
| Levels & XP | `levels_enabled`, XP rate, cooldown, level channel, game XP, no-XP channel count, level roles, XP event, level-up message |
| Voice XP | Deliberately disabled — shows as off/unconfigured (`enabled`, XP/min, daily cap) |
| Automod | Deliberately disabled — shows as off/unconfigured (which filters are on: spam, invites, external links, caps; spam threshold/window) |
| Logger | Log channels set (per category) and how many of the 29 events are on |
| Lockdown | Channels the bot currently has locked |
| WatchList | Watched user count, log channel |
| Tickets | Deliberately disabled — shows as off/unconfigured (on/off, panel channel, open ticket count, next ticket number) |
| QOTD | On/off, channel |
| Debug | On/off (global, not per-server) |
| Introductions | Intro channel, role, log channel, auto-assign/scan toggles |
| Appeals | Deliberately disabled — shows as off/unconfigured (on/off) |
| Ban log | Evidence channel |
| Timeout board | Board channel |
| Badges | Deliberately disabled — shows as off/unconfigured (custom badge count + names) |

**Seven systems are deliberately disabled** (2026-11-12): their cogs
are commented out in `bot.py` and their commands are **not
registered** on either bot — VoiceXP, Tickets, Appeals, Automod,
AutoThreads, TimeCmd, and CustomBadges. Their sections above show as
off/unconfigured. That is expected, not a fault — do not re-enable
them. (AutoThreads and TimeCmd have no section in this overview.)

## Design notes

- **One section, one store.** Each section reads its own storage
  (the async `data/DB/Storage/storage.py` helpers, the Logger's
  Postgres tables, the watchlist store, or the debug flag file) and is
  wrapped so one unreadable system shows "couldn't read" instead of
  breaking the whole overview. Sections run concurrently with
  `asyncio.gather(..., return_exceptions=True)`.
- **Storage is Postgres now.** Every section reads the shared Postgres
  database (`havenly`) — the Logger's old SQLite database and the sync
  watchlist store are gone.
- **Custom permissions are intentionally left out.** They have their
  own `/perm overview` and `/perm commands`; the overview's footer
  points there.
- **One embed per message.** Discord caps the total characters across
  all embeds in one message at 6000, not 6000 per embed, so the
  overview chunks fields (splitting on line boundaries, never
  mid-line) and sends one embed per followup message.
- **Pycord gotcha.** A command method may not start with `bot_` or
  `cog_` — the method is `show_bot_settings`, while the command name
  stays `bot_settings`.
