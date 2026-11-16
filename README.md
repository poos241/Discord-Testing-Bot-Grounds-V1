# Havenly Bot 2.0 + Havenly Helper

A Discord bot system for the **Little Haven** community, built on
[pycord](https://docs.pycord.dev/) with slash commands and organized
into **cogs** so you can add new features without touching the core
files. It runs as **two bots sharing one codebase and one database**:

| Bot | Role | Commands |
| --- | --- | --- |
| **Havenly Bot 2.0** (main bot) | The face of the system. Real-time moderation, levels, games, QOTD, help — everything a mod or member does in the moment. | 52 top-level / 81 runnable |
| **Havenly Helper** (worker bot) | The back office. Setup and config, batch jobs (scans, backfills, backups), and the timeout board. | 16 top-level / 35 runnable |

Both bots register the **same guilds** (the test server and Little
Haven) and share **five commands** — the help commands (`/help`,
`/show_tags`, `/show_categories`, `/diagnose_docs`,
`/generate_tags`), which each bot answers from its own command
list, so each bot's `/help` still shows only its own commands.
Every other command lives on exactly one bot, so there is never
any doubt which bot to use. They share one **PostgreSQL 17**
database (in Docker) and talk to each other through a small local
**bridge hub** (see [The bridge hub](#the-bridge-hub) below).

**The split, in one sentence:** if a command does something *right
now* for a member or a mod (time someone out, look up a level, run a
game round), it lives on the main bot; if it *sets something up* or
*runs a batch job* (configure a channel, scan a channel for missing
cases, take a backup), it lives on the Helper. All 22 level commands
stay on the main bot. See [Systems](#systems) below for the
per-system command lists — each list says which bot runs each
command.

> **A note on names.** This project started life as a generic
> "Discord Bot Template (Python)". It is not a template any more —
> it is the live bot for Little Haven. The repo name and the folder
> name (`Discord Bot Templet Mde With Python`) are historical; the
> systemd service names (`kushbot`, `kushweb`, `havenly-helper`)
> are also historical. They still work, so they stay.

> **Handbook.** The full documentation site (Docusaurus) is at
> <https://poos241.github.io/Discord-Testing-Bot-Grounds-V1/>.
> It covers each system in more depth than this README. This
> README is the setup + operations guide; the handbook is the
> user guide.

---

## Requirements

- **Python 3.12** (3.10+ works; the live server runs 3.12.3).
- **pip** (up to date: `pip install --upgrade pip`).
- **Docker** (for the PostgreSQL database — see
  [PostgreSQL](#postgresql)).
- A **Discord application** for each bot (main + Helper) in the
  [Discord Developer Portal](https://discord.com/developers/applications),
  each with a bot token and the right intents (see
  [Create the two Discord apps](#create-the-two-discord-apps)).
- `git` if you want to clone the repo (or download the ZIP).

---

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/poos241/Discord-Testing-Bot-Grounds-V1.git
cd Discord-Testing-Bot-Grounds-V1
```

The bot code lives in the `Discord Bot Templet Mde With Python`
folder (historical name). Everything below assumes you are in that
folder:

```bash
cd "Discord Bot Templet Mde With Python"
```

### 2. Create a virtual environment

**Windows (PowerShell):**

```powershell
python -m venv venv
venv\Scripts\activate
```

**Linux / macOS:**

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install the dependencies

```bash
pip install -r requirements.txt
```

`requirements.txt` pins the exact versions running on the live
server (py-cord 2.8.1, `databases` 0.9.0, SQLAlchemy 2.1.6,
Flask 3.1.3, `asyncpg` 0.32.0, `psycopg[binary]` 3.3.9, and the
rest). `asyncpg` and `psycopg` are the PostgreSQL drivers.

### 4. PostgreSQL

The bot stores everything in **PostgreSQL 17**, running in Docker.
There is a ready-made recipe in `servers/postgres/` (in the same
repo layout as the live server — the folder holds
`docker-compose.yml` and `.env.postgres`):

```yaml
# servers/postgres/docker-compose.yml (summary)
services:
  postgres:
    image: postgres:17
    container_name: havenly-postgres
    restart: unless-stopped
    env_file:
      - .env.postgres
    ports:
      - "127.0.0.1:5432:5432"      # localhost only — nothing outside the machine can reach it
    volumes:
      - havenly_pgdata:/var/lib/postgresql/data
```

`.env.postgres` holds the database password (strict `KEY=VALUE`,
**no spaces around `=`** — that file is read by
`docker compose`, which is pickier than the bot's `.env`).
Create the database with `docker compose up -d`, then point the
bot at it with `DATABASE_URL` (see [`.env` layout](#env-layout)).

> **The old SQLite database is frozen, not live.** The bot used
> to store everything in `bot.db` (SQLite). On 2026-11-12 the
> data moved to Postgres (bot.db 4,969 rows + message_log.db
> 2,865 rows, 0 mismatches) and the live SQLite file was frozen
> at 2026-11-12 11:41. Nothing writes to SQLite any more. The
> `bot.db` file is still in the repo folder as a legacy copy —
> do not delete it, and do not expect it to change.

### 5. Create the two Discord apps

Create **two** applications in the
[Discord Developer Portal](https://discord.com/developers/applications)
— one for Havenly Bot 2.0 (the main bot) and one for Havenly
Helper (the worker). For **each** app:

1. Create the application, then go to the **Bot** tab.
2. Under **Privileged Gateway Intents**, turn on all three:
   **Server Members Intent**, **Message Content Intent**, and
   **Presence Intent**. The Helper will not work without them.
3. Copy the bot token (Reset Token if you need to see it again).
   Each token goes in `.env` under a different name (see below).
4. Invite each bot to your server(s) with the
   `bot applications.commands` scopes. Give the main bot the
   permissions it needs for moderation (Manage Roles, Moderate
   Members, Manage Messages, Manage Channels, Ban Members,
   Kick Members, and so on — see the
   [handbook](https://poos241.github.io/Discord-Testing-Bot-Grounds-V1/)
   for the full list).

> **The Helper only syncs commands when it starts.** If you
> invite the Helper to a new server, its commands will not show
> up until you restart the `havenly-helper` service. The main
> bot syncs the same way (at startup).

### 6. `.env`

Copy `.env.example` to `.env` and fill it in. (`setup.py` does
this for you — run `python setup.py` and answer the prompts.)
Never commit `.env`.

```ini
# ---- Main bot token (required) ----
TOKEN2=<your main bot token>

# ---- Helper (worker) token (required to run the Helper) ----
WORKER_TOKEN=<your helper bot token>

# ---- Database (required) ----
DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/havenly

# ---- Bot/website bridge (required) ----
# Shared secret the bot and the website use to talk over the local
# bridge API. Without it the bridge will not start and live website
# pages degrade to "bot unavailable". Generate a long random string
# and keep it private (never commit .env).
BRIDGE_SECRET=<a long random secret — see "Generating a bridge secret" below>
# Optional: bridge ports (defaults 5001 main / 5002 worker).
# BRIDGE_PORT=5001
# WORKER_BRIDGE_PORT=5002

# ---- Uptime Kuma heartbeats (optional) ----
# KUMA_PUSH_URL=http://127.0.0.1:3001/api/push/<main bot push key>
# WORKER_KUMA_PUSH_URL=http://127.0.0.1:3001/api/push/<helper push key>
# KUMA_PUSH_INTERVAL_SECONDS=30

# ---- Web dashboard (Discord OAuth login) ----
WEB_HOST=127.0.0.1
WEB_PORT=5000
WEB_SECRET_KEY=<a random secret for web sessions>
DISCORD_CLIENT_ID=<your Discord application id>
DISCORD_CLIENT_SECRET=<your Discord application client secret>
DISCORD_REDIRECT_URI=http://127.0.0.1:5000/callback
# PUBLIC_BASE_URL=<the site's public URL, e.g. https://havenly.tailf374c5.ts.net>
# When set, the OAuth redirect is PUBLIC_BASE_URL/callback (the live
# site uses it with a Tailscale Funnel URL — see "Web dashboard" below).
# Leave it unset for a local-only install.

# ---- GitHub ban log (optional — only if you use /banlog) ----
# GITHUB_PROJECT_TOKEN=<a classic personal access token with the `project` scope>
# GITHUB_PROJECT_OWNER=<GitHub user or org that owns the ban-log board>
# GITHUB_PROJECT_NUMBER=2
```

`WEB_HOST=0.0.0.0` is what lets you open the dashboard from
another computer on the same network (and what Uptime Kuma needs
to check it). Leave it at `127.0.0.1` if the dashboard only ever
runs on the same machine as your browser.

### Generating a bridge secret

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Copy the output into `BRIDGE_SECRET` in `.env`. (On Windows,
run that in PowerShell and paste the result.)

### 7. `config.py`

`config.py` holds the server and user IDs the bot needs:

- `OWNER_IDS` — the Discord user IDs that can run owner-only
  commands (`/debug`, `/shutdown_bot`, `/restart_bot`,
  `/restart_web`).
- `GUILD_IDS` — the servers the bot registers commands in.
  The live bot is in two guilds: the test server
  (`557680433245061130`) and Little Haven
  (`1318042499784249415`).
- `BOT_OWNER_IDS` / `BOT_ADMINS` — who can approve ban-log
  entries and run admin commands.
- `MODERATOR_ROLE_IDS` / `HELPER_ROLE_IDS` — the role IDs
  that count as moderator / helper for the permission system.

Edit them in `config.py` directly. (There is also a
`config_helpers.py` with helpers for reading/writing these.)

### 8. Run it

Three processes, all separate:

| Process | Command | Service (Linux/systemd) |
| --- | --- | --- |
| Main bot | `python bot.py` | `kushbot` |
| Helper (worker) | `WORKER_MODE=1 python bot.py` | `havenly-helper` |
| Website | `python run_web.py` | `kushweb` |

**Windows** — double-click `run_bot.bat` (main bot, under its
watchdog) or `run_web.bat` (website, under its watchdog). The
Helper on Windows is `set WORKER_MODE=1` then `python bot.py`
in a third window.

**Linux (systemd, the live server):**

```bash
sudo systemctl start kushbot.service havenly-helper.service kushweb.service
sudo systemctl enable kushbot.service havenly-helper.service kushweb.service   # start on boot
```

All three services are `Restart=on-failure`, so a crash restarts
the process automatically.

The main bot and the Helper are the **same code** — the only
difference is the `WORKER_MODE` environment variable. When it is
set, `bot.py` loads the worker cog set (`WORKER_COGS`), registers
only the Helper's commands, and starts the worker bridge hub on
port 5002. When it is not set, it loads the full cog set, registers
the main bot's commands, and starts the main bridge on port 5001.
The systemd unit for the Helper sets `WORKER_MODE=1`; the
variable is **not** in `.env` (it must not be — the main bot
reads the same `.env`).

### 9. Check they're running

```bash
# Linux (systemd)
sudo systemctl status kushbot.service havenly-helper.service kushweb.service
```

Or open the website at `http://127.0.0.1:5000/` (or the server's
address, e.g. `http://<server-tailscale-ip>:5000/` on the live server).
The live site is also public at
`https://havenly.tailf374c5.ts.net` (Tailscale Funnel — see
[Web dashboard](#web-dashboard)).
The dashboard's bot-status page shows **both** bots (see
[Web dashboard](#web-dashboard)).

To check the bridges directly, read the secret from `.env`
instead of typing it:

Linux / macOS:

```bash
curl -H "X-Bridge-Secret: $(grep '^BRIDGE_SECRET=' .env | cut -d= -f2-)" http://127.0.0.1:5001/bridge/status
curl -H "X-Bridge-Secret: $(grep '^BRIDGE_SECRET=' .env | cut -d= -f2-)" http://127.0.0.1:5002/status
```

Windows (PowerShell, from the bot folder):

```powershell
$s = (Select-String -Path .env -Pattern '^BRIDGE_SECRET=').Line -replace '^BRIDGE_SECRET=',''; curl.exe -H "X-Bridge-Secret: $s" http://127.0.0.1:5001/bridge/status
```

---

## Useful commands

### Start / stop / restart

**Windows** — close the console window for the process you want
to stop, then double-click the matching `.bat` to start it again
(`run_bot.bat` for the main bot, `run_web.bat` for the website).

**Linux (systemd):**

```bash
sudo systemctl restart kushbot.service          # main bot
sudo systemctl restart havenly-helper.service   # Helper
sudo systemctl restart kushweb.service          # website
sudo systemctl restart kushbot.service kushweb.service havenly-helper.service   # all three
```

From Discord (main bot, owner-only): `/restart_bot` restarts the
main bot, `/restart_web` restarts the website. There is no
Discord command to restart the Helper — restart it with
`systemctl` (that is deliberate: the same command name doing
different things on two bots would be confusing).

### Logs

**Windows** — the bot and website each log to their own console
window (the one `run_bot.bat` / `run_web.bat` opened).

**Linux (systemd):**

```bash
journalctl -u kushbot.service -n 50 --no-pager        # main bot, last 50 lines
journalctl -u havenly-helper.service -n 50 --no-pager # Helper, last 50 lines
journalctl -u kushweb.service -n 50 --no-pager        # website, last 50 lines
journalctl -u kushbot.service -f                      # follow the main bot log live
```

### Update the code

```bash
git pull                 # from the repo root, on any machine
git log --oneline -3     # what version is running?
git rev-parse HEAD       # the exact commit
git status --short       # any local changes?
```

After a pull, restart the side that changed (`sudo systemctl
restart kushbot.service kushweb.service havenly-helper.service`
on the server, or close and re-run the `.bat` files on Windows).
Dashboard-only changes need only the website restarted; the bot
doesn't need to restart for those.

### Python and packages

```bash
python --version         # Windows
python3 --version        # Linux / macOS
python -m py_compile bot.py    # syntax-check a file without running it
```

Install a package into the bot's venv (make sure
`requirements.txt` lists it so a fresh install gets it):

```bash
venv\Scripts\activate     # Windows, then pip install <name>
pip install <name>        # (inside the venv)
```

Linux:

```bash
.venv/bin/pip install <name>   # from the repo root
```

---

## Uptime Kuma

Uptime Kuma (running in Docker on the home server, web UI at
http://127.0.0.1:3001 on that machine) watches all three sides —
but each side is watched a different way, because they are
separate processes:

**Website — HTTP check (Kuma pulls).** Create a monitor of type
HTTP(s), URL `http://<server-tailscale-ip>:5000/` (the server's Tailscale
address — the website binds `0.0.0.0`, so Kuma in Docker can reach
it). A 200 means the website is up.

**Main bot — Push check (the bot pushes).** The bot has no HTTP
endpoint of its own (the bridge is localhost-only and the bot-status
pages need a login), so it pushes its own heartbeat to Kuma:

1. In Kuma, create a monitor of type **Push**. Set its **Heartbeat
   Interval to 60s**.
2. Kuma shows a push URL like
   `http://127.0.0.1:3001/api/push/<key>`. Copy the key part — the
   bot runs on the same machine as Kuma, so use the `127.0.0.1`
   form even if Kuma displays a different host (Kuma's port is
   only published on localhost, so any other host won't connect).
3. Add one line to the bot's `.env` (same file as the token):

   ```
   KUMA_PUSH_URL=http://127.0.0.1:3001/api/push/<the key Kuma gave you>
   ```

   The push URL is a key: never commit it, never share it.
4. Restart the bot (`/restart_bot` in Discord, or the dashboard
   Restart bot button). The bot pushes every 30s; Kuma marks it
   DOWN if no push arrives within its 60s interval.

**Helper — Push check (same shape, separate monitor).**
Create a second Push monitor named "Havenly Helper" (60/60) and
add its URL to `.env` as `WORKER_KUMA_PUSH_URL`, then restart the
Helper. Until the monitor exists, the Helper's heartbeat is
disabled — check its health with `systemctl status
havenly-helper` or the worker bridge `/status` endpoint instead.

Optional: `KUMA_PUSH_INTERVAL_SECONDS=30` in `.env` changes how
often the bots push (default 30). Keep the push interval at half
Kuma's Heartbeat Interval or less, so normal jitter never flaps
the monitor.

If a push URL is not set, that bot's heartbeat is off and it logs
a `[KUMA] ... heartbeat disabled` line once at startup. A failed
push logs `[KUMA] Push failed: ...` and the bot keeps going — one
failed push never stops the heartbeat.

---

## Project structure

```
Discord-Testing-Bot-Grounds-V1/
├── README.md               # This file (repo root)
├── servers/
│   └── postgres/
│       ├── docker-compose.yml   # Postgres 17 container (havenly-postgres)
│       └── .env.postgres        # Database password (never commit)
└── Discord Bot Templet Mde With Python/     # the bot + website code
    ├── bot.py                  # Entry point: loads token, intents, and cogs; WORKER_MODE picks main vs Helper
    ├── bridge_api.py           # Bot-side bridge API (main 5001 / worker 5002) the website talks to
    ├── run_web.py              # Standalone website entry point (python run_web.py)
    ├── watchdog.py             # Auto-restart watchdog for the bot and the website (exit 1/42 relaunch, 0 stops)
    ├── run_bot.bat             # Double-click to start the bot under its watchdog
    ├── run_web.bat             # Double-click to start the website under its watchdog
    ├── config.py               # Server/user IDs, responses, permission checks, JSON helpers
    ├── requirements.txt        # Python dependencies (incl. Flask for the web dashboard)
    ├── .env                    # Tokens + DATABASE_URL + BRIDGE_SECRET + web secrets (you create this — never commit it)
    ├── .env.example            # Template for .env (placeholders only)
    ├── setup.py                # Interactive setup: creates .env, checks the Discord token
    ├── bot.db                  # LEGACY frozen SQLite copy (2026-11-12) — do not edit, nothing writes to it
    ├── data/                   # Runtime data (backups, logs, caches — never committed)
    │   └── DB/
    │       └── db.py           # Database layer (Postgres; the SQLite fallback is legacy)
    ├── utils/
    │   ├── backup.py           # Snapshot / restore (pg_dump based)
    │   └── permissions.py      # Custom per-command permission checks
    ├── web/                    # Web dashboard (Flask, separate process — see section below)
    │   ├── app.py              # App factory + blueprint registration
    │   ├── serve.py            # Waitress server + host/port resolution
    │   ├── blueprints/         # One file per page/API area (profiles, backups, directory, feed, friends, voice, ...)
    │   ├── templates/          # Jinja pages
    │   ├── static/             # CSS/JS + user background uploads (never committed)
    │   ├── services/           # Bridge client (bridge.py), local async loop (local_loop.py), permissions, Discord state
    │   └── security/           # Login/permission decorators
    ├── website/
    │   └── docs/               # Handbook source (Docusaurus)
    └── cogs/
        ├── admin_cog.py        # Moderation + process commands (see Moderation)
        ├── fun_cog.py          # Eat It or Yeet It party game
        ├── Level_system.py     # Message XP, levels, leaderboard
        ├── WatchList.py        # Watch List system
        ├── DebugCog.py         # /debug toggle + logging
        ├── QOTD.py             # Question of the Day
        ├── Backup.py           # Backup + restore (worker only)
        ├── Lockdown.py         # Lockdown + slowmode
        ├── GHLog.py            # GitHub ban log
        ├── Introduction.py     # Introduction tracking
        ├── Modlogs.py          # Modlog viewer + edit
        ├── Permissions.py      # Custom per-command permissions (worker only)
        ├── ServerSettings.py   # /bot_settings (worker only)
        ├── Help_Info_Doc.py    # /help and the docs commands
        └── Logger/             # Server event logging (listeners on the main bot, config on the Helper)
            ├── __init__.py     # Registers all Logger cogs
            ├── config.py       # Log categories, colors, channel names
            ├── database.py     # Postgres tables for log config, toggles, event history
            ├── logger.py       # Sends embeds to configured log channels
            ├── base.py         # BaseLogger cog (shared send/audit helpers)
            ├── embeds.py       # LoggerEmbed builders
            ├── messages.py     # MessageLogger: edits, deletes, bulk deletes
            └── ...              # One file per event area (members, voice, server, moderation, roles, ...)
```

> **Cogs that are deliberately disabled.** Six cogs are commented
> out in `bot.py` and their commands are **not registered** on either
> bot: Tickets, Appeals, Automod, AutoThreads, TimeCmd, and
> CustomBadges. That is intentional (disabled 2026-11-12) —
> do not uncomment them, and do not expect their commands to exist.
> Their files are still in `cogs/` for reference. (VoiceXP was in
> this list too, but it was re-enabled on 2026-11-14 — voice XP is
> back, merged into the level system; see [Levels](#levels).)

---

## Systems

Every command in the bot belongs to a system, and every system
below lists its commands with the bot that runs each one.
**Main** = Havenly Bot 2.0. **Helper** = Havenly Helper.

Command counts are the live Discord registrations (verified
2026-11-16 against the Discord API on both guilds): **main 52
top-level / 81 runnable, Helper 16 top-level / 35 runnable, 5
shared** (the help commands — `/help`, `/show_tags`,
`/show_categories`, `/diagnose_docs`, `/generate_tags` — which
each bot answers from its own command list). If a command is not
listed here, it is not registered on either bot.

### Moderation

The day-to-day mod toolkit: time members out, purge a user's
messages, look a member up, manage roles, and rename users. All
of it runs on the **main bot** (the face of the system) — the
mod actions are real-time, so they belong where the mod is
already talking.

`/userinfo` opens a panel with action buttons (warn, timeout,
kick, ban, clear, notes, watch, add XP) and respects the custom
permission system (see [Custom permissions](#custom-permissions)).

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/timeout` | Main | Time a member out (preset durations or a custom length, up to 28 days). | Mod+ |
| `/clear_user` | Main | Delete a user's messages from a channel (or all channels). | Mod+ |
| `/userinfo` | Main | Show a member's info panel (roles, join date, mod history, XP) with action buttons. | Mod+ |
| `/add_user_role` | Main | Give a member a role. | Mod+ |
| `/remove_user_role` | Main | Take a role from a member. | Mod+ |
| `/rename_bot` | Main | Change the bot's nickname. | Admin |
| `/rename_user` | Main | Change a member's nickname. | Mod+ |
| `/reset_user_name` | Main | Reset a member's nickname to their username. | Mod+ |
| `/restart_bot` | Main | Restart the main bot process. | Owner only |
| `/restart_web` | Main | Restart the website process. | Owner only |
| `/shutdown_bot` | Main | Shut the main bot down. | Owner only |

The timeout board (the "Active Timeouts" embed) is a separate
system — see [Timeout board](#timeout-board).

### Timeout board

One "Active Timeouts" embed per guild, soonest first (cap 25,
"+N more"), refreshed whenever a timeout changes and every 5
minutes. It is owned by the **Helper**: the worker runs the
board-refresh loop, and the setup command lives there too.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/timeout_board` | Helper | Set, move, or remove the Active Timeouts board in a channel. | Admin |

Timeout presets: Light 5m, Short 15m, Medium 1h, Long 1d,
Extended 1w, Severe 2w, plus free-form up to 28d. If a timeout
already exists, `/timeout` offers Replace or Cancel.

> **Known issue:** the test guild's board message was authored
> by the old Kush Bush bot, so neither current bot can edit it
> (403). Re-set the board with `/timeout_board` (on the Helper)
> to get a board the Helper owns.

### Levels

The level system awards XP for messages, voice time, games, and
daily claims, and shows it on rank cards and a leaderboard. **All
22 level commands live on the main bot** — the main bot owns
level writes, so nothing can double-award XP.

- **Level N needs N × 100 XP.** Levels are per-server.
- The level system is **off by default per guild** — an admin
  turns it on with `/toggle_levels`. While it is off, no XP is
  earned from messages, games, voice, or manual grants, and
  `/daily`, `/add_xp`, and the `/userinfo` add-XP button refuse.
- **Voice XP is merged into levels** (no separate voice bar):
  automatic for everyone, no opt-in. With at least one other
  real human in the voice channel you earn 1–10 random XP per
  minute; alone, 1–10 random XP every 5th solo minute. No daily
  cap; muted or deafened members still earn. AFK and stage
  channels are excluded, and `/no_xp_bulk` has a voice-only
  picker for the no-voice-XP ("sleep") channel list.
- **`/level` sends the rank card** (the same Little Haven
  pink/purple night-sky card `/rank` used to send — `/rank` was
  removed 2026-11-16 because the two were identical). `/cardcolor`
  changes the XP bar colour on the card. The next role reward and
  daily streak still show, as message text under the card.
- **Thread XP is off by default** (flipped 2026-11-14); game XP
  and thread XP are toggles inside `/no_xp_bulk` now — the
  standalone `/toggle_thread_xp` and `/toggle_game_xp` commands
  are gone.
- **Spam channel:** `/set_spam_channel` picks one channel where
  `/level` works; outside it, `/level` answers with an ephemeral
  redirect to that channel. `/toggle_level_messages` works
  anywhere. When no spam channel is set, `/level` works anywhere.
- **Level-up messages:** if a level channel is set, level-ups
  post there. If no channel is set, a level-up from a slash
  command (`/daily`, `/add_xp`) is an ephemeral reply only the
  invoker sees, and a level-up from message or voice XP stays
  silent. There are no level-up DMs. Each user can silence
  their own level messages with `/toggle_level_messages`. The
  level-up card has the Little Haven nebula background
  (`cogs/levelup_bg.png`).
- XP events multiply XP for a window (`/xp_event` /
  `/xp_event_end`). Note: `/xp_event` is global while
  `/xp_event_end` is guild-scoped — that asymmetry is a known
  quirk, not a feature.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/level` | Main | Show your (or a member's) level, XP, and rank card. | Everyone |
| `/leaderboard` | Main | Show the server XP leaderboard. | Everyone |
| `/daily` | Main | Claim your daily XP (with a streak). | Everyone |
| `/cardcolor` | Main | Pick your rank-card colour. | Everyone |
| `/add_xp` | Main | Give XP to a member. | Mod+ |
| `/resetxp` | Main | Reset a member's XP. | Admin |
| `/cleardata` | Main | Wipe a member's level data. | Admin |
| `/getxpsettings` | Main | Show the level settings for this server. | Admin |
| `/level_settings` | Main | Show / change the level settings (XP rate, cooldowns, roles). | Admin |
| `/set_xp_rate` | Main | Set the XP multiplier. | Admin |
| `/set_cooldown` | Main | Set the XP cooldown between messages. | Admin |
| `/set_level_channel` | Main | Set (or remove) the channel level-ups post to. | Admin |
| `/set_spam_channel` | Main | Set (or remove) the channel `/level` works in. | Admin |
| `/set_level_role` | Main | Set a role awarded at a level. | Admin |
| `/remove_level_role` | Main | Remove a level role. | Admin |
| `/set_levelup_message` | Main | Set the level-up message template. | Admin |
| `/toggle_levels` | Main | Turn the level system on/off for this server. | Admin |
| `/toggle_level_messages` | Main | Opt in/out of your own level-up messages. | Everyone |
| `/toggle_no_xp` | Main | Turn XP on/off for one channel. | Admin |
| `/no_xp_bulk` | Main | Turn XP on/off for up to 25 channels at once; also flips Thread XP / Game XP and manages the no-voice-XP channel list. | Admin |
| `/xp_event` | Main | Start an XP event (multiplier for a window). | Admin |
| `/xp_event_end` | Main | End the current XP event. | Admin |

### Eat It or Yeet It

A party game: the bot posts a food, players vote **Eat It** or
**Yeet It**, and the majority wins. Game XP is awarded per vote
(10 XP) plus a majority bonus. The game runs on the **main
bot** only — if the Helper ran it too, rounds and XP would
double.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/eatyeet` | Main | Start a round. | Everyone (host) |
| `/eatyeet_end` | Main | End the current round. | Host / Mod |
| `/eatyeet_leaderboard` | Main | Show the game leaderboard. | Everyone |
| `/eatyeet_stats` | Main | Show your (or a member's) game stats. | Everyone |
| `/eatyeet_suggest` | Main | Suggest a food for the game. | Everyone |
| `/eatyeet_history` | Main | Show recent rounds. | Everyone |

### Question of the Day (QOTD)

A daily question posted to a channel, with a suggestion flow:
members suggest questions with `/qotd submit`, mods approve or
reject them with `/qotd approve` / `/qotd reject`, and the
approved pool is what gets posted. The pool is **296 approved
questions** (60 original + 146 SIEL + 90 Conversation Starters).
Posting is the **main bot's** job (so nothing double-posts); the
config lives on the **Helper**.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/qotd today` | Main | Show today's question. | Everyone |
| `/qotd history` | Main | Show past questions. | Everyone |
| `/qotd submit` | Main | Suggest a question (goes to mod approval). | Everyone |
| `/qotd post` | Main | Post a question now. | Mod+ |
| `/qotd skip` | Main | Skip today's question. | Mod+ |
| `/qotd pending` | Main | List questions waiting for approval. | Mod+ |
| `/qotd approve` | Main | Approve a pending question. | Mod+ |
| `/qotd reject` | Main | Reject a pending question. | Mod+ |
| `/qotd remove` | Main | Remove a question from the pool. | Mod+ |
| `/qotd config` | Helper | Set the QOTD channel, time, and posting options. | Admin |

### Introduction tracking

Tracks whether members have posted an introduction. The **main
bot** watches the intro channel in real time (its listeners are
gated to the main bot) and answers the "does this member have an
intro?" queries; the **Helper** owns the setup and the batch
backfill scan.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/intro check` | Main | Check whether a member has posted an intro. | Mod+ |
| `Check Introduction` | Main | Right-click a member → check their intro (context menu). | Mod+ |
| `/intro set_channel` | Helper | Set the channel intros are tracked in. | Admin |
| `/intro set_role` | Helper | Set the role given to members who have introduced themselves. | Admin |
| `/intro settings` | Helper | Show the intro tracking setup. | Admin |
| `/intro toggle` | Helper | Turn a tracking behaviour on/off. | Admin |
| `/intro scan` | Helper | Scan the intro channel and mark everyone who already posted (backfill). | Admin |

> **Server-side fix needed (test guild):** intro tracking fails
> silently there until two things are fixed in the server
> settings — drag the intro role **below** Havenly Bot 2.0's
> top role, and give the bot View + Send in the intro log
> channel. Only a server admin can do that.

### Modlogs

A searchable record of moderation cases. Mods look cases up on
the **main bot**; the batch scan that backfills cases from the
mod-log channel lives on the **Helper**.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/modlogs list` | Main | List mod cases (filterable). | Mod+ |
| `/modlogs recap` | Main | Summarise a member's mod history. | Mod+ |
| `/modlogs edit` | Main | Edit a mod case. | Mod+ |
| `/modlogs actions` | Main | Look up the actions on a case. | Mod+ |
| `/modlogs scan` | Helper | Scan the mod-log channel and add missing cases (backfill). | Admin |

### GitHub ban log (GHLog)

Logs bans (and kicks) to a **GitHub Project board** so the mod
team has a durable, reviewable record. A mod logs a ban in the
moment on the **main bot**; the batch jobs (collecting evidence
screenshots, backfilling case numbers) run on the **Helper**.

The flow: `/banlog log` creates a pending entry → a second mod
reviews it with `/banlog approve`. **A mod can never approve
their own entry** — the self-approve bypass was removed from the
code in 2026-11-06, and there is no way to turn it back on.

Setup: a classic personal access token with the `project` scope
(`GITHUB_PROJECT_TOKEN`), the board owner (`GITHUB_PROJECT_OWNER`)
and the board number (`GITHUB_PROJECT_NUMBER`, default 2). The
live test board is `poos241` project 2; the real Little Haven
board is `Spiderella007` project 2 ("Little Haven Bans").

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/banlog log` | Main | Log a ban/kick to the GitHub board (creates a pending entry). | Mod+ |
| `/banlog approve` | Main | Approve a pending ban-log entry. | Mod+ (never the author) |
| `/banlog update` | Main | Update a ban-log case. | Mod+ |
| `/banlog delete` | Main | Delete a ban-log case. | Mod+ |
| `/banlog set_channel` | Helper | Set the evidence channel for ban-log screenshots. | Admin |
| `/banlog collect` | Helper | Collect screenshots sent in a channel into a log's evidence thread. | Admin |
| `/banlog backfill_cases` | Helper | Give a case number to board entries that don't have one. | Admin |

> **Status:** ban-log improvements are paused (2026-11-04).
> Going live on the real board still needs the narrow-token
> swap and flipping `GITHUB_PROJECT_OWNER` to `Spiderella007`.

### Logger

Server event logging: message edits/deletes, member joins/leaves,
voice activity, server changes, moderation actions, role changes.
Events are posted as embeds to per-category log channels. The
whole Logger system — config and toggles — lives on the
**Helper**; the main bot does the actual event logging (its
listeners are the ones that see the events).

- `/logs setup` takes up to 4 optional channels (bind instead
  of create, validated for bot send first). The `create_channels`
  option (default off) is opt-in: only turn it on if you want
  the bot to create the log channels for you.
- Role logs skip the intro role and are batched (5-minute
  inactivity / 30-minute max wait, one "Roles Updated" embed per
  user). Pending batches are lost if the bot restarts.
- There are 29 per-event toggles, split across 5 `/log_toggle`
  groups (message, member, voice, server, moderation).

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/logs setup` | Helper | Set up the log channels (bind existing or create). | Admin |
| `/logs change_channel` | Helper | Change one log channel. | Admin |
| `/logs settings` | Helper | Show the Logger setup and toggles. | Admin |
| `/log_toggle message` | Helper | Toggle message-event logging. | Admin |
| `/log_toggle member` | Helper | Toggle member-event logging. | Admin |
| `/log_toggle voice` | Helper | Toggle voice-event logging. | Admin |
| `/log_toggle server` | Helper | Toggle server-event logging. | Admin |
| `/log_toggle moderation` | Helper | Toggle moderation-event logging. | Admin |

### Watch List

A mod tool for keeping an eye on specific members: when a watched
user posts, the message is logged to the watch channel. All the
day-to-day watch management is on the **main bot**; the channel
setup is on the **Helper**.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/watch add` | Main | Watch a member (by mention). | Mod+ |
| `/watch remove` | Main | Stop watching a member. | Mod+ |
| `/watch add_id` | Main | Watch a member by user ID. | Mod+ |
| `/watch remove_id` | Main | Stop watching a member by user ID. | Mod+ |
| `/watch list` | Main | List watched members. | Mod+ |
| `/watch status` | Main | Show the watch system status. | Mod+ |
| `/watch info` | Main | Show details for one watched member. | Mod+ |
| `/watch clear` | Main | Clear the whole watch list. | Admin |
| `/watch set_channel` | Helper | Set the channel watch logs go to. | Admin |

### Custom permissions

A per-command allow/deny list that **replaces** the default
Discord permission check for any command it covers (REPLACE
semantics — a grant overrides the Discord check, it does not add
to it). Server admins are always allowed. Precedence: admin >
user deny > user allow > role deny > role allow > default Discord
check > deny when rules exist but don't match. Grants live in the
shared `command_permissions` table in Postgres, so they apply to
**both** bots — and because of that, the whole `/perm` group lives
on the **Helper**, while mods manage grants for every command
(including main-bot commands) from there.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/perm allow` | Helper | Allow a user/role to run a command. | Admin |
| `/perm remove` | Helper | Remove a permission grant. | Admin |
| `/perm list` | Helper | List the grants for a command (or all). | Admin |
| `/perm bulk` | Helper | Apply grants to many commands at once. | Admin |
| `/perm commands` | Helper | List the commands that can be granted. | Admin |
| `/perm overview` | Helper | Show the permission setup at a glance. | Admin |
| `/perm reset` | Helper | Reset permissions for a command. | Admin |

### Bot settings

A read-only overview of every bot system's on/off state and key
config, in one place. It is an admin view, and it lives on the
**Helper**.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/bot_settings` | Helper | Show every bot system's state and key config. | Admin (grantable) |

### Backup

Snapshots of the database (a `pg_dump` plus a manifest, zipped).
The **Helper** owns backups: its daily loop takes a snapshot at
04:00, and the manual commands live there too. Retention: the
newest 14 daily snapshots + the newest 10 manual / pre-restore
snapshots; older ones are pruned automatically.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/backup now` | Helper | Take a snapshot now. | Admin |
| `/backup status` | Helper | Show the latest snapshot. | Admin |

Restore from a snapshot with `psql` (see the
[handbook](https://poos241.github.io/Discord-Testing-Bot-Grounds-V1/)).

**Off-site backup.** Every night at 02:30 (after the 02:00 local
backup), the latest snapshot's `bot.dump` is uploaded to a private
Google Drive folder, encrypted with rclone (`gdrive-crypt` wraps
`gdrive:Havenly-Backups`, filename + directory encryption on).
The upload script (`~/bin/drive-backup.sh`, cron
`30 2 * * *`) uploads **only** the dump — never `.env` or tokens —
and verifies it with `rclone check` before logging. Each night
uploads a dated file (`bot-YYYY-MM-DD.dump`); files older than
14 days are pruned, but only after a successful upload + verify.
The crypt password is the recovery key: lose it and the Drive
backups are unreadable. It lives in Emily's password manager
(and in the Nitro's rclone config) — it is not recorded anywhere
in this repo.

### Lockdown

Lock and unlock channels in a hurry (raid / spam response), with
an auto-unlock timer. Real-time moderation, so it lives on the
**main bot**.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/lockdown lock` | Main | Lock one channel. | Mod+ |
| `/lockdown unlock` | Main | Unlock one channel. | Mod+ |
| `/lockdown lockall` | Main | Lock all channels. | Admin |
| `/lockdown unlockall` | Main | Unlock all channels. | Admin |
| `/lockdown slowmode` | Main | Set slowmode on a channel. | Mod+ |
| `/lockdown status` | Main | Show the lockdown state. | Mod+ |

### Help & docs

The in-Discord help system. `/help` lists the commands **you**
can use (it filters by the permission system, fail-closed — if
you can't run a command, it doesn't show up). The help commands
are the one shared set: they live on **both** bots, and because
`/help` reads the bot's own registered command list, each bot's
`/help` naturally shows only its own commands.

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/help` | Both | Show the commands you can use. | Everyone |
| `/show_tags` | Both | Show the help tags. | Everyone |
| `/show_categories` | Both | Show the help categories. | Everyone |
| `/diagnose_docs` | Both | Diagnose the docs data. | Admin |
| `/generate_tags` | Both | Regenerate the help tags. | Admin |

### Debug

Owner-only toggles for the **main bot** (verbose logging and a
test command).

| Command | Bot | What it does | Who can run it |
| --- | --- | --- | --- |
| `/debug on` | Main | Turn debug logging on. | Owner only |
| `/debug off` | Main | Turn debug logging off. | Owner only |
| `/debug status` | Main | Show the debug state. | Owner only |
| `/debug test` | Main | Run a debug test. | Owner only |

---

## Web dashboard

A Flask website (separate process, `python run_web.py`) that
gives the community a web front end for the bot: public profiles
with level rings, tags, and showcases, a server directory, a
leaderboard, an activity feed, a friends system, voice status,
backups, and a mod panel. It uses Discord OAuth for login
(`identify` + `guilds` scopes).

**Public access.** The live site is public at
`https://havenly.tailf374c5.ts.net` via **Tailscale Funnel**
(no open router ports, home IP hidden, HTTPS only — only the
website on port 5000 is exposed). `PUBLIC_BASE_URL` in `.env`
is set to that URL, which is also the Discord OAuth redirect
base (`PUBLIC_BASE_URL/callback`). When a domain is bought
later, the plan is a Cloudflare Tunnel pointed at it.

The website talks to the bots through the **bridge hub**:

| | Main bot bridge | Helper bridge |
| --- | --- | --- |
| Address | `127.0.0.1:5001` | `127.0.0.1:5002` |
| Auth | `X-Bridge-Secret` header | `X-Bridge-Secret` header |
| What it does | Full API (moderation actions, profiles, levels, backups, …) | Status + jobs only (`backup_now`, `board_refresh`, `main_status`) |

The website reaches **both** bots — `GET /api/bots` returns the
status of the main bot and the Helper, so the dashboard's
bot-status page shows both. A wrong bridge secret gets a 401 and
an unknown job gets a 404 on both bridges.

**Profiles are opt-in and private by default.** A member's
profile shows sensitive details publicly only if they opt in.
There is a per-user toggle to silence level messages while still
earning XP, and the level system itself is off until an admin
turns it on (see [Levels](#levels)).

**Web permissions.** The dashboard has its own permission layer
that reuses the Discord custom-permission system, so Discord
and web grants stay in sync (same `command_permissions` table
in Postgres). Every guild page is gated in this order:

1. **Owner bypass** — Emily and the guild owner always get in,
   plus anyone on the editable **bypass list** (a
   `web_bypass_users` table, managed from the Permissions page;
   the two seeded users — Emily and the Little Haven owner —
   are permanent and cannot be removed). Bypassed users skip
   every other check, including the unverified gate, and bypass
   changes take effect on the next page load.
2. **Unverified role** — members holding the guild's configured
   unverified role (Little Haven: `1411162751304470578`, set on
   the Permissions page) cannot open any guild page until
   RaidProtect removes the role (captcha solved). Re-checked
   fresh on every page load. There is no "verified" role — the
   unverified role is the whole gate.
3. **Permission for the action** — website actions map to Discord
   command permissions (`timeout`, `kick`, `ban`, `warn`,
   `clear_user`, …) or to `web:` keys for web-only actions
   (`web:view_dashboard`, `web:manage_permissions`,
   `web:manage_logs`, `web:manage_notes`, `web:wipe_member`).
   With no custom rules, `web:view_dashboard` defaults to the
   moderator tier and the other `web:*` keys default to admin.

Each major site section also has its own view key, so a role can
be let into one section and kept out of another:
`web:view_members`, `web:view_leaderboard`, `web:view_channels`,
`web:view_roles`, `web:view_logger`, `web:view_activity`,
`web:view_voice` (all moderator-tier by default). Overview and
Server home stay on the baseline `web:view_dashboard`. Viewing
the Logger is `web:view_logger`; changing Logger settings is
still `web:manage_logs` (admin-only by default). The sidebar
hides every link the viewer cannot open.

The **Permissions page** (`/servers/<gid>/permissions`, also
home to the Logger Settings tab) is where grants are managed:
bulk-add any number of roles and/or pasted user IDs against any
number of grouped actions (Allow or Deny, one submit per
target × action), a **custom-action field** for a command or
`web:` key that is not in the picker, and the current-rules list
(grouped by action, filterable, bulk-remove, collapsible
groups, and the name — not just the ID — of who added each
rule). The website's OAuth is `identify` + `guilds` only — it
does not get role IDs from Discord, so role-based gating is done
against the bot's own data (the bot is the source of truth via
the bridge `web_access` route).

**Web theme + layout.** The site uses the handbook theme
(pink/purple/indigo, dark default; one shared
`web/static/css/havenly-theme.css`). The dashboard, members,
and logger pages have been laid out in that theme (sticky
headers, sticky sidebars, mobile off-canvas navigation). The
three logger pages are merged into one Logger page with tabs
(Event History, Live auto-refreshing every 10s, Analytics), and
Logger Settings lives as a tab on the Permissions page. Clicking
an event opens an Event Details card with clean labeled fields,
a "Go to message" jump link, and Before/After side by side for
message edits.

**Mod actions on the web.** Warn, timeout, kick, rename, and
strip-roles stop with "This member is no longer in the server"
when the target has left the server (nothing is recorded). Ban
is deliberately unchanged — banning someone who is not in the
server is legitimate (ban them so they cannot rejoin).

> **Never hard-refresh the dashboard to fix a stale page.**
> The dashboard handles cache-busting itself (versioned JS/CSS
> filenames). If a page looks stale, restart the website
> (`sudo systemctl restart kushweb.service`) and check again.

---

## Adding a new cog

1. Create `cogs/MyCog.py` with a class that extends
   `commands.Cog` and a `setup` function that adds it to the bot.
2. Add `"cogs.MyCog"` to `COGS` in `bot.py` — or to
   `WORKER_COGS` if the cog belongs on the Helper.
3. **Decide which bot the commands go on first.** Real-time
   user/mod actions go on the main bot; setup/config and batch
   jobs go on the Helper. If a cog has commands for both bots,
   gate each command definition with a `WORKER_MODE` check at
   class level (see `cogs/Introduction.py` for the pattern) — a
   command only exists on the class in the matching mode, so it
   only registers on that bot.
4. **Count before you add a top-level command.** Discord caps
   guild application commands at 100 per guild. The main bot is
   at 52, the Helper at 16 — plenty of headroom, but count first
   and verify the sync actually registered the command (see the
   Discord API check in [Troubleshooting](#troubleshooting)).
5. Restart the bot that owns the new command and check it shows
   up in Discord. (The Helper only syncs at startup, so a
   restart is required for its commands to appear.)

See `DEVELOPER.md` and the
[handbook](https://poos241.github.io/Discord-Testing-Bot-Grounds-V1/)
for the cog conventions (views, buttons, embeds, the permission
check, and the database layer).

---

## Debug mode

`/debug on` (owner only, main bot) turns on verbose logging for
the main bot — useful when a command is misbehaving and you need
to see what the bot is doing. `/debug status` shows whether it
is on, `/debug off` turns it off, `/debug test` runs a test
command. Debug output goes to the bot's log (console window on
Windows, `journalctl -u kushbot.service` on Linux).

---

## Recent changes

A short changelog of the big moves. The full detail lives in the
handbook and in the work records under `~/workspace/pubwork/`.

- **2026-11-16 — Logger card + perms additions + rules list.**
  The Logger Event Details card was rebuilt (clean labeled
  fields, "Go to message" jump link, Before/After side by side,
  no duplicated Details block). The Permissions page gained a
  custom-action field (type in a command or `web:` key that is
  not in the picker) and an editable bypass list (new
  `web_bypass_users` table; seeded users are permanent). The
  current-rules list now shows the *name* of who added each rule
  and is collapsible, with a sticky filter toolbar. `/rank`
  was removed (`/level` already sends the same rank card) —
  live counts: main 52/81, Helper 16/35.
- **2026-11-16 — Per-section web permissions.** Each site
  section has its own view key (`web:view_members`,
  `web:view_leaderboard`, `web:view_channels`, `web:view_roles`,
  `web:view_logger`, `web:view_activity`, `web:view_voice`),
  moderator-tier by default, so a role can see the Logger but
  not the Members list. Logger viewing moved from
  `web:manage_logs` (admin-only) to `web:view_logger`;
  Logger settings stay admin-only.
- **2026-11-15/16 — Public site + web permission system.**
  The site is public at `https://havenly.tailf374c5.ts.net`
  (Tailscale Funnel; Discord OAuth moved to the Havenly Bot 2.0
  app, redirect `…/callback`). The web permission system went
  live: gate order bypass → unverified role → permission, with
  `web:` keys and a Permissions page (bulk add/remove, unverified
  role setting). The handbook theme rolled out site-wide, the
  dashboard/members/logger pages were laid out in it, the
  logger pages merged into one tabbed page, and the Logger
  Settings merged into the Permissions page. Warn/timeout/kick/
  rename/strip-roles now stop for members who have left the
  server (ban unchanged). A stale-session CSRF bug and the
  website's missing database connection were fixed.
- **2026-11-14/15 — Level system round.** Voice XP merged into
  levels (automatic, single bar, 1–10/min with someone, 1–10
  every 5th solo minute, no cap, muted/deafened still earn).
  `/level` sends the rank card and `/cardcolor` colours its XP
  bar (next role reward + daily streak kept as text).
  `/set_spam_channel` added; thread XP defaults off; the
  standalone thread/game XP toggles moved into `/no_xp_bulk`.
  Level-up and rank cards share the Little Haven nebula
  background.
- **2026-11-13 — Command split (Option C).** The two bots now
  have zero shared commands: setup/config and batch jobs moved
  to the Helper (`/perm`, `/logs`, `/bot_settings`, `/backup`,
  `/timeout_board`, the `/intro` setup commands, the scan/collect
  jobs); the main bot keeps all real-time use commands and all
  24 level commands. Live counts: main 54/83, Helper 11/30.
  Two cache bugs fixed so Helper-made setup changes take effect
  live (Introduction config now has a 60s TTL; WatchList reloads
  fresh on every call).
- **2026-11-12/13 — Havenly Helper invited to Little Haven.**
  The Helper's commands did not show up until a restart — the
  worker only syncs at startup, so inviting it to a new guild
  needs a restart before its commands appear there.
- **2026-11-12 — Postgres cutover.** All data moved from
  SQLite (`bot.db`) to PostgreSQL 17 in Docker. Live SQLite is
  frozen. The `databases` 0.9.0 connect race was fixed by
  serialising `connect()` (one `asyncio.Lock`) and connecting
  once in `on_ready`.
- **2026-11-12 — Havenly Helper goes live.** Second bot, same
  codebase, `WORKER_MODE` flag. Bridge hub added (worker on
  5002). Website now sees both bots (`GET /api/bots`). E2E test
  23/23 pass.
- **2026-11-11 — Command merge.** The bot hit Discord's
  100-command cap (103 top-level, sync failed 400/30032), so
  command families were merged into groups (`/perm`, `/watch`,
  `/intro`, `/modlogs`, `/banlog`, `/auto_thread`, `/logs`) —
  103 → 68 top-level. `/testbanlog` was deleted. 18 stored
  permission grants were auto-migrated at boot. (`/auto_thread`
  is not registered now — AutoThreads is one of the deliberately
  disabled cogs, see [Project structure](#project-structure).)
- **2026-11-11 — Level settings + Logger rounds.**
  `/level_settings` and `/toggle_thread_xp` added;
  `/logs setup` gained an opt-in `create_channels` flag
  (default off).
- **2026-11-10 — Four fixes + rebrand.** Eat It or Yeet It
  run-it-back kills old buttons; `/help` filters to commands
  the invoker can use; ban embeds restyled to the original
  Havenly "User Banned"; Logger role logs batch. Rebrand to
  "Havenly Bot" / "Little Haven" (footers, website brand).
- **2026-11-10 — QOTD pool.** 296 approved questions (60
  original + 146 SIEL + 90 Conversation Starters), with the
  suggest-with-mod-approval flow.
- **2026-11-09 — Level-up delivery.** No more level-up DMs: a
  level channel posts publicly, otherwise slash-command XP
  level-ups are ephemeral followups and message/voice XP
  level-ups stay silent. `/add_xp` and `/daily` defer
  ephemeral from the start.
- **2026-11-08 — Little Haven data migration.** 1,160 intros,
  812 mod cases, 373 VRChat accounts, 2,519 profiles moved
  from the old bot's database. `/modlogs scan` built to backfill
  missing cases.
- **2026-11-06 — Ban-log self-approve bypass removed.** The
  `/banlog approve` flow always refuses self-approval now; the
  `GHLOG_ALLOW_SELF_APPROVE` environment variable does nothing.
- **2026-11-05 — Custom permissions + level controls + bot
  settings.** Per-command allow/deny (REPLACE semantics),
  `/bot_settings`, level system off by default per guild,
  `/no_xp_bulk`, `/toggle_level_messages`.
- **October 2026 — Building-mode batch + security audits.**
  The web UI overhaul (gating, public profiles, SQLite
  migration with JSON backup, activity feed, level rings, tags,
  showcase, pronouns/display name, custom pfp/banner/background,
  uploads max 5 MB, notification bell, XP orb, opt-in
  color-coded server roles) and the October + November security
  audits (117 findings in the November audit; the GHLog
  self-approve bypass was removed as a result). See the
  handbook for the full history.

---

## Troubleshooting

- **A command doesn't show up in Discord** — the bot only
  syncs commands at startup. Restart the bot that owns it
  (`sudo systemctl restart kushbot.service` for the main bot,
  `sudo systemctl restart havenly-helper.service` for the
  Helper). This is the most common cause after inviting the
  Helper to a new server.
- **The Helper's commands are missing on a guild it just joined**
  — same as above: restart `havenly-helper`. The worker does
  not re-sync on guild join.
- **`/shutdown_bot` says you're not authorized** — your user ID
  isn't in `OWNER_IDS` in `config.py`.
- **The website says "bot unavailable"** — the bridge is down
  or the secret is wrong. Check the bot is running
  (`systemctl status kushbot.service`), check `BRIDGE_SECRET`
  matches in the bot's `.env` and the website's `.env` (they are
  the same file — one `.env` serves both processes), and curl
  `/bridge/status` (see [Check they're running](#9-check-theyre-running)).
- **The website shows the Helper as down** — check the Helper
  is running (`systemctl status havenly-helper.service`) and
  that `WORKER_BRIDGE_PORT` (default 5002) is reachable from the
  website process.
- **Postgres won't start** — check Docker is running, check
  `.env.postgres` has strict `KEY=VALUE` with **no spaces**
  around `=`, and check the container logs:
  `docker logs havenly-postgres`.
- **The bot can't connect to Postgres** — check
  `DATABASE_URL` in `.env` (one line, `postgresql://...`),
  check the container is healthy (`docker ps` /
  `pg_isready`), and check the bot's log for the connection
  error. The live `.env` uses CRLF line endings with spaces
  around `=` — if you edit it by hand, keep the format the
  bot expects.
- **`pip install` fails on `databases`** — make sure you're on
  Python 3.10+ and pip is up to date
  (`pip install --upgrade pip`).
- **A slash command fails with "The application did not
  respond"** — the bot probably hit an error before answering.
  Check the bot's log (`journalctl -u kushbot.service -n 50`
  for the main bot, `journalctl -u havenly-helper.service -n 50`
  for the Helper) — the traceback is there.
- **How to verify the live command counts** — the Discord API
  is the source of truth, not the code. A bot can restart
  healthy and still have commands that never went live. Use
  the probe script (`scripts/dump_cmds.py` in the work records)
  or the Discord API directly:
  `GET /applications/<app id>/guilds/<guild id>/commands`
  with the bot's token. The live counts (2026-11-16) are main
  52 top-level / 81 runnable on both guilds, Helper 16
  top-level / 35 runnable on both guilds, 5 shared (the help
  commands).
- **Something worked on the test server but not Little Haven
  (or vice versa)** — check `GUILD_IDS` in `config.py` (the
  live bot registers in both guilds) and check the command
  actually exists on the right bot (see the counts above).
  Remember the Helper's commands only appear after a restart.
