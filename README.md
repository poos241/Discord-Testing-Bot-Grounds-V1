# Discord Bot Template (Python)

A starter template for building a Discord bot in Python. It's built on
**pycord**, uses slash commands, and organizes features into **cogs** so you
can add new ones without touching the core files.

**What it comes with out of the box:**
- Slash commands that sync automatically on startup
- Admin cog: user info, clearing a user's messages, adding/removing roles,
  renaming the bot or users, and owner-only shutdown/restart commands
- A rotating bot status (cycles through messages every 10–60 seconds)
- SQLite database layer (SQLAlchemy + `databases`) with tables for levels/XP,
  profiles, tickets, appeals, voice XP, lockdowns, automod, badges, friends,
  and more (see the building-mode batch below)
- JSON helper functions for the few remaining small files (notification read
  state); game, mod, and watch data moved to SQLite in October 2026
- Permission-check decorators (`admin_required`, `is_owner`, etc.) in `config.py`

> The bot code lives in the `Discord Bot Templet Mde With Python` folder —
> that's the project root you'll work from below.

---

## Requirements

- **Python 3.10 or newer** ([python.org/downloads](https://www.python.org/downloads/))
- **pip** (comes with Python)
- A Discord application with a bot token — created free at the
  [Discord Developer Portal](https://discord.com/developers/applications)

## Setup

### 1. Clone the repo

```bash
git clone https://github.com/poos241/Discord-Testing-Bot-Grounds-V1.git
cd "Discord-Testing-Bot-Grounds-V1/Discord Bot Templet Mde With Python"
```

### 2. (Recommended) Create a virtual environment

Windows:
```bash
python -m venv venv
venv\Scripts\activate
```

Mac / Linux:
```bash
python3 -m venv venv
source venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

Or run the one-shot setup script instead — it checks your Python version,
installs everything, verifies the imports, creates your `.env`, and
syntax-checks the cogs:

```bash
python setup.py
```

### 4. Create your bot in the Discord Developer Portal

1. Go to the [Developer Portal](https://discord.com/developers/applications)
   and click **New Application** — give it a name.
2. Open the **Bot** tab, click **Reset Token**, and copy the token.
   **Keep this secret — never share it or commit it to GitHub.**
3. In the **Bot** tab, under *Privileged Gateway Intents*, turn on
   **Server Members Intent**, **Message Content Intent** (the Logger needs
   it to log message text), and **Presence Intent** (online/offline status
   on the web dashboard).
4. Open the **OAuth2 → URL Generator** tab, tick the scopes
   `bot` and `applications.commands`, then pick bot permissions
   (for a test bot, `Administrator` is easiest).
5. Copy the generated URL at the bottom, open it in your browser, and add
   the bot to your server.

### 5. Add your token

Create a file named `.env` in the project folder (next to `bot.py`)
with this inside:

```
TOKEN2=paste-your-bot-token-here
```

The website talks to the bot over a private local bridge (see
"Bot + website: two separate processes" below), and the bridge needs
its own shared secret — a long random string only the bot and the
website know. Add one more line to the same `.env` file:

```
BRIDGE_SECRET=paste-a-long-random-secret-here
```

Without `BRIDGE_SECRET` the bridge refuses to start and every live
website page degrades to "bot unavailable" by design (the bot itself
still runs fine). Optional: `BRIDGE_PORT=5001` changes the bridge
port (default `5001`); `BRIDGE_ENABLED=0` turns the bridge off
entirely. Never commit `.env` — it holds your bot token and this
secret.

### 6. (Optional) Edit `config.py` for your server

- `OWNER_IDS` — put your Discord user ID(s) here. Required for
  `/shutdown_bot` and `/restart_bot`. (Right-click yourself in Discord →
  Copy User ID; enable Developer Mode first if you don't see it.)
- `GUILD_IDS` — your test server ID(s).
- `statuses` — the list of messages the bot cycles through as its status.

### 7. Run the bot and the website (two separate processes)

Since November 2026 the bot and the website run as **separate
processes**, each with its own auto-restart watchdog (see "Bot +
website: two separate processes" below). Start each one its own way:

**Bot** — double-click `run_bot.bat`, or in a terminal:

```bash
python bot.py
```

You should see `[OK] Logged in as YourBot#1234 ... Commands synced!` in
the console, then `[OK] Bridge API listening on http://127.0.0.1:5001`.
The SQLite database (`bot.db` at the bot folder root) is created automatically on first run. Commands are guild-scoped (`GUILD_IDS` in
`config.py`), so they sync on startup and show up within seconds.

**Website** — double-click `run_web.bat`, or in a terminal:

```bash
python run_web.py
```

It serves on `http://127.0.0.1:5000` by default. The order doesn't
matter — each side tolerates the other being down (the website shows
"bot unavailable" on live pages while the bot is off, instead of
crashing). `run_bot.bat` / `run_web.bat` run a watchdog around each
process: a crash (exit 1) or a restart request (exit 42) relaunches
that side only; a clean stop (exit 0) stays stopped; more than 5
restarts in 60 seconds stops loudly instead of looping forever.

---

## Project structure

```
Discord Bot Templet Mde With Python/
├── bot.py                  # Entry point: loads token, intents, and cogs; starts the bridge API
├── bridge_api.py           # Bot-side bridge API (127.0.0.1:5001) the standalone website talks to
├── run_web.py              # Standalone website entry point (python run_web.py)
├── watchdog.py             # Auto-restart watchdog for the bot and the website (exit 1/42 relaunch, 0 stops)
├── run_bot.bat             # Double-click to start the bot under its watchdog
├── run_web.bat             # Double-click to start the website under its watchdog
├── config.py               # Server/user IDs, responses, permission checks, JSON helpers
├── requirements.txt        # Python dependencies (incl. Flask for the web dashboard)
├── .env                    # Your bot token + BRIDGE_SECRET + web dashboard secrets (you create this — never commit it)
├── web/                    # Web dashboard (Flask, separate process — see section below)
│   ├── app.py              # App factory + blueprint registration
│   ├── serve.py            # Waitress server + host/port resolution
│   ├── blueprints/         # One file per page/API area (profiles, backups, directory, feed, friends, voice, ...)
│   ├── templates/          # Jinja pages
│   ├── static/             # CSS/JS + user background uploads (never committed)
│   ├── services/           # Bridge client (bridge.py), local async loop (local_loop.py), permissions, Discord state
│   └── security/           # Login/permission decorators
├── cogs/
│   ├── admin_cog.py        # Admin slash commands (see table below)
│   ├── fun_cog.py          # Eat It or Yeet It party game (see section below)
│   ├── Level_system.py     # Message XP, levels, leaderboard (see section below)
│   ├── WatchList.py        # Watch List system: log watched users' messages (see section below)
│   ├── DebugCog.py         # /debug toggle + logging
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
│   ├── GHLog.py            # GitHub ban log (see section below)
│   ├── Introduction.py     # Introduction tracking (see section below)
│   ├── Modlogs.py          # Modlog viewer + edit (see section below)
│   └── Logger/             # Server event logging (see section below)
│       ├── __init__.py     # Registers all Logger cogs
│       ├── config.py       # Log categories, colors, channel names
│       ├── database.py     # SQLite: message cache, log channel config, toggles, event history
│       ├── logger.py       # Sends embeds to configured log channels
│       ├── base.py         # BaseLogger cog (shared send/audit helpers)
│       ├── embeds.py       # LoggerEmbed builders
│       ├── messages.py     # MessageLogger: edits, deletes, bulk deletes
│       ├── members.py      # MemberLogger: joins, leaves, nick/avatar/role changes
│       ├── channels.py     # ChannelLogger: channel + thread create/delete/update
│       ├── emoji.py        # EmojiLogger: emoji create/delete/rename
│       ├── moderation.py   # ModerationLogger: bans, unbans, timeouts
│       ├── voice.py        # VoiceLogger: joins, leaves, moves, mute/deafen
│       ├── invites.py      # InviteLogger: invite create/delete
│       ├── roles.py        # RoleLogger: role create/delete/update
│       ├── commands.py     # /setup_logs, /change_logchannel, /log_settings, /log_toggle
│       └── audit.py        # Audit-log lookup (target-matched)
├── bot.db                  # Live SQLite database (bot folder root, not data/)
├── data/
│   ├── eatyeet_*.json      # Legacy rollback copies (live data is SQLite now)
│   ├── watchlist_data.json # Legacy rollback copy (live data is SQLite now)
│   ├── mod_data.json       # Legacy rollback copy (live data is SQLite now)
│   ├── notification_read.json # Notification bell read/dismissed state
│   ├── message_log.db      # Logger: cached messages + log channel config
│   └── DB/
│       ├── db.py           # Database connection (SQLite)
│       ├── models.py       # Table definitions
│       └── Storage/
│           └── storage.py  # Async get/save helpers for each table
└── utils/
    ├── data_utils.py       # Simple JSON load/save helpers
    ├── backup.py           # Snapshot/restore engine
    ├── github_projects.py  # GitHub Projects v2 API client (GraphQL, for GHLog)
    └── json_sqlite_store.py # Lazy JSON→SQLite store
```

## 📖 Complete command reference

Every slash command (and the one context-menu command) in the bot,
built from the actual code — **127 slash commands + 1 user
context-menu command = 128 commands**. If a command isn't listed
here, it doesn't exist. Commands are guild-scoped to `GUILD_IDS` in
`config.py` (currently the test server only) unless the Scope column
says **Global** — global commands register in every server the bot
is in and can take up to an hour to appear after a restart, while
guild-scoped ones show up within seconds.

**Gates:** Administrator = Discord Administrator permission;
Manage Server / Admin = Manage Server or Administrator;
Manage Messages / Manage Channels = that Discord permission
(Administrators pass automatically); Bot owner = your user ID in
`OWNER_IDS` in `config.py`; Staff (tickets/appeals) = the role set
with `/ticket config` / `/appeal config`, falling back to
Manage Messages / Administrator when no role is set. "No gate"
means any member can run it.

**Worth knowing:** `/xp_event` is global while `/xp_event_end` is
guild-scoped (looks unintentional — a one-line fix if it ever
matters). `/log_settings` is the only staff-facing command with no
gate at all — anyone can view the Logger configuration (the reply
is ephemeral). The `/debug` refusal text says "You need Manage
Server permission" but the code also accepts Administrator.

### admin_cog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/timeout` | Times out a member, with a preset length or a free-form duration (max 28d); asks to replace if they already have an active timeout. | `member` (Member, required); `preset` (optional; Light—5m, Short—15m, Medium—1h, Long—1d, Extended—1w, Severe—2w); `duration` (optional string, e.g. `1h30m`); `reason` (optional, default "No reason given") | Manage Server / Admin (in-callback `_is_manager`) | Guild |
| `/timeout_board` | Posts, moves, shows, or removes the "Active Timeouts" board (lists every active Discord timeout and tempban, soonest expiry first, auto-refreshing). | `channel` (TextChannel, optional — where to post/move the board); `remove` (bool, optional, default false) | Manage Server / Admin (in-callback `_is_manager`) | Guild |
| `/clear_user` | Deletes a user's messages in one channel or all channels. | `target_user` (User, optional); `user_id` (string, optional, for users who left); `channel` (TextChannel, optional); `amount` (int, optional, default 100) | Administrator | Global |
| `/userinfo` | Shows a detailed user card with a self-updating mini mod panel (see panel paragraph at the end). | `member` (Member, optional); `user` (string, optional — user ID, mention, or username); `private` (bool, optional, default true — only you see the card); `test_mode` (bool, optional, default false — simulates actions) | Administrator | Guild |
| `/remove_user_role` | Removes a role from a user. | `member` (Member, required); `role` (Role, required) | Administrator | Global |
| `/add_user_role` | Gives a role to a user. | `member` (Member, required); `role` (Role, required) | Administrator | Global |
| `/rename_bot` | Changes the bot's nickname in the server. | `new_nick` (string, required) | Administrator | Global |
| `/rename_user` | Changes a user's nickname. | `member` (Member, required); `new_nick` (string, required) | Administrator | Global |
| `/reset_user_name` | Clears a user's nickname (removes the custom nickname). | `member` (Member, required) | Administrator | Global |
| `/shutdown_bot` | Shuts the bot down (stays down until restarted). | none | Bot owner only | Global |
| `/restart_bot` | Restarts the bot. | none | Bot owner only | Global |

### fun_cog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/eatyeet` | Starts a round of Eat It or Yeet It. | `duration` (int, optional, default 30s; choices: 30s, 1h, 2h, 4h, 8h, 12h, 24h); `source` (string, optional, default auto; Auto = mix of API + local, Local list only, API only) | No gate (everyone) | Guild |
| `/eatyeet_end` | Ends the active round in this channel early. | none | Round starter or Administrator (in-callback) | Guild |
| `/eatyeet_leaderboard` | Shows the top 10 players by points. | none | No gate (everyone) | Guild |
| `/eatyeet_stats` | Shows a player's rounds played, points, majority-vote rate, and streaks. | `user` (User, optional — defaults to you) | No gate (everyone) | Guild |
| `/eatyeet_suggest` | Suggests a food for the community pool (credited to you). | `food` (string, required, 3–100 chars) | No gate (everyone) | Guild |
| `/eatyeet_history` | Shows the last 10 finished rounds with foods and verdicts. | none | No gate (everyone) | Guild |

### Level_system

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/set_xp_rate` | Sets the min/max XP gained per message. | `minimum` (int, required); `maximum` (int, required) | Administrator | Guild |
| `/set_cooldown` | Sets the cooldown in seconds between XP gains per user (0 = no cooldown). | `seconds` (int, required) | Administrator | Guild |
| `/set_level_channel` | Sets the channel where level-up messages are posted. | `channel` (TextChannel, required) | Administrator | Guild |
| `/level` | Shows your (or another member's) level and XP progress. | `member` (Member, optional) | No gate (everyone) | Guild |
| `/leaderboard` | Shows the top 10 users by level and XP. | none | No gate (everyone) | Guild |
| `/add_xp` | Adds XP to a user (level-ups are announced like normal). | `member` (Member, required); `amount` (int, required) | Administrator | Guild |
| `/resetxp` | Resets a user's XP to 0 and level to 1. | `member` (Member, required) | Administrator | Guild |
| `/cleardata` | Clears all level data for this server. | none | Administrator | Guild |
| `/getxpsettings` | Shows the server's XP settings (rate, cooldown, level-up channel/message, role rewards, no-XP channels, XP events, game XP toggle). | none | No gate (everyone) | Guild |
| `/set_level_role` | Sets a role reward for reaching a level (cumulative). | `level` (int, required); `role` (Role, required) | Administrator | Guild |
| `/remove_level_role` | Removes a level's role reward (members who already have it keep it). | `level` (int, required) | Administrator | Guild |
| `/toggle_game_xp` | Toggles level XP earned by voting in Eat It or Yeet It (on by default). | none | Administrator | Guild |
| `/toggle_no_xp` | Toggles message XP on/off for a channel. | `channel` (TextChannel, required) | Administrator | Guild |
| `/xp_event` | Starts a server-wide bonus XP multiplier event (multiplier 2–5). | `minutes` (int, required); `multiplier` (int, optional, default 2) | Administrator | **Global** (no `guild_ids=` — the only Level command that is global) |
| `/xp_event_end` | Ends a running XP event early. | none | Administrator | Guild |
| `/daily` | Claims your daily XP bonus (once every 20h; consecutive-day streaks earn more). | none | No gate (everyone) | Guild |
| `/cardcolor` | Sets your rank/level-up card accent color (hex, preset name, or `reset`). | `color` (string, required) | No gate (everyone) | Guild |
| `/set_levelup_message` | Sets a custom level-up announcement (`{user}`, `{name}`, `{level}`); run with no text to reset to default. | `message` (string, optional) | Administrator | Guild |
| `/rank` | Shows your rank card image (level, XP progress, server rank). | `member` (Member, optional) | No gate (everyone) | Guild |

### VoiceXP

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/voicexp optin` | Opts you in to earning XP for time in voice channels (needs 1+ other non-bot person; muted/deafened/AFK time never counts). | none | No gate (everyone) | Guild |
| `/voicexp optout` | Opts you out of voice XP (banked totals are kept). | none | No gate (everyone) | Guild |
| `/voicexp status` | Shows your (or another member's) voice XP stats (opt-in state, total voice time/XP, today's cap progress). | `member` (Member, optional) | No gate (everyone) | Guild |
| `/voicexp leaderboard` | Shows the top 10 by total qualifying voice time (with voice XP). | none | No gate (everyone) | Guild |
| `/voicexp config` | Shows the server's voice XP settings (enabled state, rate, cap, opt-in count). | none | Administrator | Guild |
| `/voicexp setrate` | Sets XP earned per minute of voice time (1–10, default 1). | `rate` (int, required) | Administrator | Guild |
| `/voicexp setcap` | Sets the daily voice XP cap per user (0 = no cap, default 100 XP per UTC day). | `cap` (int, required) | Administrator | Guild |
| `/voicexp enable` | Enables voice XP for this server. | none | Administrator | Guild |
| `/voicexp disable` | Disables voice XP for this server (banked totals and opt-ins are kept). | none | Administrator | Guild |

### WatchList

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/watch_add` | Adds a user to the watch list (their messages are logged to the watch channel). | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_remove` | Removes a user from the watch list. | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_add_id` | Adds a user to the watch list by Discord ID (or mention). | `user_id` (string, required) | Manage Server / Admin | Global |
| `/watch_remove_id` | Removes a user from the watch list by Discord ID. | `user_id` (string, required) | Manage Server / Admin | Global |
| `/watch_list` | Shows everyone on the watch list. | none | Manage Server / Admin | Global |
| `/watch_status` | Shows watch-list status (user count, log channel, logging state). | none | Manage Server / Admin | Global |
| `/watch_info` | Shows details about one watched user (who added them and when). | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_set_channel` | Sets the channel where watched users' messages are logged. | `channel` (TextChannel, required) | Manage Server / Admin | Global |
| `/watch_clear` | Removes everyone from the watch list (with confirmation; already-sent logs are kept). | none | Manage Server / Admin | Global |

### DebugCog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/debug on` | Enables debug logging (persists via `data/.debug_enabled`). | none | Administrator or Manage Server | Guild |
| `/debug off` | Disables debug logging. | none | Administrator or Manage Server | Guild |
| `/debug status` | Shows whether debug mode is on or off. | none | Administrator or Manage Server | Guild |
| `/debug test` | Prints a test debug line to the console + `data/debug.log`. | none | Administrator or Manage Server | Guild |

### QOTD

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/qotd today` | Shows today's Question of the Day. | none | No gate (everyone) | Guild |
| `/qotd history` | Looks back at past Questions of the Day. | `count` (int, optional, default 7, 1–25) | No gate (everyone) | Guild |
| `/qotd submit` | Submits a question for a future QOTD (10–500 characters). | `question` (string, required) | No gate (everyone) | Guild |
| `/qotd post` | Posts today's question right now. | none | Manage Messages / Admin | Guild |
| `/qotd skip` | Replaces today's question with a fresh one. | none | Manage Messages / Admin | Guild |
| `/qotd config` | Sets the QOTD channel, post time, timezone, or on/off. | `channel` (TextChannel, optional); `post_time` (string, optional, HH:MM 24-hour); `timezone` (string, optional, autocomplete); `enabled` (bool, optional) | Manage Messages / Admin | Guild |
| `/qotd pending` | Lists submitted questions waiting for approval. | none | Manage Messages / Admin | Guild |
| `/qotd approve` | Approves a submitted question into the rotation. | `question_id` (int, required — the pending question's #id) | Manage Messages / Admin | Guild |
| `/qotd reject` | Rejects a submitted question. | `question_id` (int, required) | Manage Messages / Admin | Guild |
| `/qotd remove` | Removes a question from this server's rotation. | `question_id` (int, required — from history or a post) | Manage Messages / Admin | Guild |

### Tickets

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/ticket panel` | Posts the ticket panel in this channel (members click it to open a ticket). | none | Manage Messages / Admin | Guild |
| `/ticket config` | Sets the ticket settings for this server. | `staff_role` (Role, optional); `category` (CategoryChannel, optional); `log_channel` (TextChannel, optional); `panel_channel` (TextChannel, optional) | Manage Messages / Admin | Guild |
| `/ticket show` | Shows the ticket settings for this server. | none | Manage Messages / Admin | Guild |
| `/ticket open` | Opens a support ticket (one open ticket per user). | `topic` (string, optional) | No gate (everyone) | Guild |
| `/ticket close` | Closes this ticket. | `reason` (string, optional) | Ticket opener or staff | Guild |
| `/ticket reopen` | Reopens this closed ticket. | none | Ticket opener or staff | Guild |
| `/ticket claim` | Claims (or releases) this ticket. | none | Staff only | Guild |
| `/ticket delete` | Deletes this closed ticket's channel (only works on closed tickets). | none | Staff only | Guild |
| `/ticket add` | Adds a member to this ticket channel. | `member` (Member, required) | Staff only | Guild |
| `/ticket remove` | Removes a member from this ticket channel (cannot remove the opener). | `member` (Member, required) | Staff only | Guild |
| `/ticket list` | Lists this server's open tickets. | none | Manage Messages / Admin | Guild |

### Backup

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/backup now` | Takes a backup snapshot right now. | none | Manage Messages / Admin | Guild |
| `/backup status` | Shows the latest backup snapshot. | none | Manage Messages / Admin | Guild |

### Appeals

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/appeal submit` | Appeals a ban or timeout. (In DMs it redirects you to DM the bot the word `appeal`.) | `appeal_type` (string, required; choices: `ban`, `timeout`); `details` (string, required, max 1000 chars) | No gate (everyone); one pending appeal per user | Guild |
| `/appeal list` | Lists appeals, newest first (max 20 shown). | `status` (string, optional, default `pending`; choices: `pending`, `approved`, `denied`, `all`) | Appeal staff (configured staff role, else Manage Messages / Admin; Admins always pass) | Guild |
| `/appeal review` | Reviews one appeal (shows it with Approve/Deny buttons). | `appeal_id` (int, required — appeal number, e.g. 3) | Appeal staff (same as above) | Guild |
| `/appeal config` | Sets the appeals channel / staff role (run with no options to view current settings). | `channel` (TextChannel, optional); `staff_role` (Role, optional) | Manage Server / Admin | Guild |
| `/modnotes search` | Keyword search across mod notes, warns, and cases. | `keyword` (string, required); `user` (Member, optional — only search this member's records) | Manage Messages / Admin | Guild |

### Lockdown

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/lockdown lock` | Locks a channel so @everyone cannot send messages (restores the previous permission on unlock); a duration sets a timed lock that auto-unlocks. | `channel` (TextChannel, optional — defaults to current channel); `duration` (int, optional — minutes); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown unlock` | Unlocks a channel, restoring its previous @everyone permission. | `channel` (TextChannel, optional — defaults to current channel) | Manage Channels | Guild |
| `/lockdown lockall` | Locks every text channel in the server (skips forum channels and channels already bot-locked). | `duration` (int, optional — minutes); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown unlockall` | Unlocks every channel the bot has locked in this server. | none | Manage Channels | Guild |
| `/lockdown slowmode` | Sets slowmode on a channel (0 turns it off). | `seconds` (int, required, 0–21600); `channel` (TextChannel, optional — defaults to current channel); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown status` | Shows every channel the bot currently has locked, with pending auto-unlocks. | none | Manage Channels | Guild |

### Automod

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/automod status` | Shows the automod rules and spam settings for this server. | none | Manage Messages | Guild |
| `/automod toggle` | Turns one automod rule on or off (leave `enabled` blank to flip it). | `rule` (string, required — `spam`, `invites`, `external_links`, `caps`); `enabled` (bool, optional) | Manage Messages | Guild |
| `/automod config` | Sets the spam burst threshold and window. | `threshold` (int, optional, 1–50); `window` (int, optional, 5–300 seconds) | Manage Messages | Guild |

### AutoThreads

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/auto_thread` | Toggles auto-threads for the channel the command is run in (default 24h archive, no name prefix; does not work in threads or DMs). | none | Manage Channels | Guild |
| `/set_auto_thread_channel` | Designates a channel for auto-threads, or updates its settings. | `channel` (TextChannel, required); `archive_minutes` (int, optional — 60, 1440, 4320, or 10080; blank keeps current); `name_prefix` (string, optional — text put in front of every thread name) | Manage Channels | Guild |
| `/remove_auto_thread_channel` | Stops auto-threading a channel (existing threads are left alone). | `channel` (TextChannel, required) | Manage Channels | Guild |
| `/auto_thread_status` | Lists every channel designated for auto-threads, with archive setting and name prefix. | none | Manage Channels | Guild |

### TimeCmd

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/time` | Shows a member's local time from their profile timezone (blank = yourself; someone else's time only shows if they opted in to sharing local info). | `user` (Member, optional) | No gate (everyone) | Guild |

### CustomBadges

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/badge create` | Creates a custom badge for this server (name becomes its per-server slug). | `name` (string, required); `icon` (string, optional, default medal emoji); `description` (string, optional — tooltip text) | Manage Messages | Guild |
| `/badge award` | Awards a custom badge to a member (appears on their profile badge shelf + activity feed). | `badge_ref` (string, required, autocomplete — badge name/slug); `member` (Member, required) | Manage Messages | Guild |
| `/badge remove` | Revokes a member's custom badge (the badge definition stays). | `badge_ref` (string, required, autocomplete); `member` (Member, required) | Manage Messages | Guild |
| `/badge delete` | Deletes a custom badge and all of its awards (cannot be undone). | `badge_ref` (string, required, autocomplete) | Manage Messages | Guild |
| `/badge list` | Lists this server's custom badges and award counts. | none | Manage Messages | Guild |

### GHLog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/testbanlog` | Posts a clearly-marked TEST draft item to the test GitHub project (proves the bot can reach GitHub Projects). | none | Administrator | Guild |
| `/banlog` | Logs a ban or kick to the GitHub ban-log project (preview + confirm first; nothing posts until confirmed). | `action` (string, required; choices: `Ban`, `Kick`); `reason` (string, required); `member` (Member, optional — pick if still in server); `user_id` (string, optional — ID, mention, or username if they left); `status` (string, optional; choices: `Preds`, `Intolerance e.g. transphobia, racism etc`, `Trolls/Bullies`, `Advertisers/Scammers`, `Misc`); `tags` (string, optional; choices: `more info`, `Blacklist approved`); `evidence` (string, optional — links separated by spaces); `screenshot` (Attachment, optional) | Manage Server / Admin (in-callback) | Guild |
| `/banlog_update` | Updates the most recent logged case for a user (Status and/or tags, and/or appends a dated note). | `member` (Member, optional); `user_id` (string, optional); `status` (string, optional; same choices as /banlog); `tags` (string, optional; same choices); `note` (string, optional) | Manage Server / Admin (in-callback) | Guild |
| `/banlog_delete` | Deletes the most recent logged case for a user (type `DELETE` exactly to confirm; cannot be undone). | `member` (Member, optional); `user_id` (string, optional); `confirm` (string, optional in the form but enforced in code — anything other than `DELETE` refuses; kept optional because Discord rejects a command when a required option follows optional ones) | Manage Server / Admin (in-callback) | Guild |

### Introduction

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/intro_set_channel` | Sets the introductions channel (and optional log channel). | `channel` (TextChannel, required); `log_channel` (TextChannel, optional) | Manage Server / Admin | Guild |
| `/intro_set_role` | Sets the role given to members who post an introduction. | `role` (Role, required) | Manage Server / Admin | Guild |
| `/intro_settings` | Shows the introduction tracking setup for this server. | none | Manage Server / Admin | Guild |
| `/intro_toggle` | Turns an introduction tracking behaviour on or off (leave `value` blank to flip it). | `setting` (string, required; choices: `auto_assign_role`, `auto_remove_role`, `scan_on_message`); `value` (bool, optional) | Manage Server / Admin | Guild |
| `/intro_scan` | Scans the intro channel and marks everyone who already posted (up to 1000 recent messages). | `limit` (int, optional, default 100, 1–1000); `add_role` (bool, optional, default true) | Manage Messages / Admin | Guild |
| `/intro_check` | Checks whether a member has posted an introduction. | `member` (Member, optional); `user_id` (string, optional — raw user ID for members who left) | Manage Messages / Admin | Guild |
| **Check Introduction** (user context-menu command — right-click a user → Apps) | Same check as `/intro_check` for that member. | (the clicked user) | Manage Messages / Admin | Guild |

### Modlogs

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/modlogs` | Browses moderation cases, newest first (filter by user, type, or date). | `member` (Member, optional); `user_id` (string, optional — raw ID for users who left); `type` (string, optional; choices: `warn`, `timeout`, `untimeout`, `kick`, `ban`, `tempban`, `unban`, `clear`, `strip_roles`, `wipe`); `before` (string, optional — only cases before YYYY-MM-DD); `after` (string, optional — only cases from YYYY-MM-DD) | Manage Server / Admin | Guild |
| `/modlogs_recap` | Counts by action type, most recent case, and tempban status for one user. | `member` (Member, optional); `user_id` (string, optional) | Manage Server / Admin | Guild |
| `/modlogs_edit` | Picks one of a user's recent cases to edit its reason or delete it. | `member` (Member, optional); `user_id` (string, optional) | Manage Server / Admin | Guild |
| `/mod_actions` | Lists every moderation action performed by one moderator. | `moderator` (Member, required) | Manage Server / Admin | Guild |

### Logger

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/setup_logs` | Creates the log channels and configures the Logger system. | none | Administrator (`@commands.has_permissions(administrator=True)`) | Guild |
| `/change_logchannel` | Points one log category at a different channel. | `log_type` (string, required; choices: `message`, `member`, `server`, `moderation`); `channel` (TextChannel, required) | Administrator (in-callback) | Guild |
| `/log_settings` | Shows the Logger configuration (which channel each category logs to + disabled events). | none | **No gate — anyone can run it** (ephemeral reply) | Guild |
| `/log_toggle message` | Toggles message event logging. | `event` (string, required; choices: `message_edit`, `message_delete`, `bulk_delete`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle member` | Toggles member event logging. | `event` (string, required; choices: `member_join`, `member_leave`, `member_kick`, `nickname`, `avatar`, `role_member`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle voice` | Toggles voice event logging. | `event` (string, required; choices: `voice_join`, `voice_leave`, `voice_move`, `voice_mute`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle server` | Toggles server event logging. | `event` (string, required; choices: `channel_create`, `channel_delete`, `channel_update`, `thread_create`, `thread_delete`, `emoji_create`, `emoji_delete`, `emoji_rename`, `role_create`, `role_delete`, `role_update`, `invite_create`, `invite_delete`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle moderation` | Toggles moderation event logging. | `event` (string, required; choices: `ban`, `unban`, `timeout`); `enabled` (bool, required) | Administrator (in-callback) | Guild |

## Built-in commands (admin cog)

The admin commands — `/userinfo` and its mod panel, `/timeout` and
`/timeout_board`, `/clear_user`, the role commands, the renames, and
owner-only `/shutdown_bot` / `/restart_bot` — are listed with full
options and gates in the [Complete command reference](#-complete-command-reference)
above. The `/userinfo` panel itself is described under Watch List
below.

## 👁️ Watch List system

Moderators can put users on a per-server watch list — every message a
watched user sends is mirrored to a configured log channel (with author,
channel, timestamps, content, attachments, stickers, and a jump link).
State lives in SQLite (`watchlist_data` table; the old JSON file is kept
as a rollback copy). All commands need **Manage
Server** or **Administrator**.

| Command | What it does | Who can use it |
|---|---|---|
| `/watch_add` | Add a user via the member picker | Manage Server / Admin |
| `/watch_remove` | Remove a user via the member picker | Manage Server / Admin |
| `/watch_add_id` | Add by raw Discord ID | Manage Server / Admin |
| `/watch_remove_id` | Remove by raw Discord ID | Manage Server / Admin |
| `/watch_list` | Show everyone on the watch list | Manage Server / Admin |
| `/watch_status` | System status (count, log channel, logging state) | Manage Server / Admin |
| `/watch_info` | Who added a watched user, and when | Manage Server / Admin |
| `/watch_set_channel` | Set the log channel | Manage Server / Admin |
| `/watch_clear` | Remove everyone (with confirmation) | Manage Server / Admin |

`/userinfo` also shows whether a user is on the watch list. Its card carries a mini mod panel: **Warn**, **Timeout** (duration like `10m`/`2h`/`1d`), **Kick**, **Ban** (with message-delete days and optional tempban duration like `7d`, auto-unbanned), **Clear**, **Notes**, **Watch**, **Add XP**, **Remove XP**, **Wipe Data**, **History**, **Rename**, and **Strip Roles** buttons — each action asks for a reason and DMs it to the user; Ban flips to **Unban**, Timeout flips to **Remove timeout**, and Watch flips to **Unwatch** when one is active; Clear opens a channel picker (or an All-channels button) then asks how many messages or `all`; Notes keeps a numbered mod-notes list you can add to and remove from; Watch asks for an optional reason and the card shows who added them, when, and why; Add/Remove XP lets you correct someone's XP (adding uses the normal level-up path); a `test_mode` true/false option simulates the actions without applying them; and a `private` option (default on) keeps the card to yourself — turn it off to post publicly. Every warn/timeout/kick/ban/clear/wipe/rename/strip is saved to the user's case history, viewable with the **History** button (newest first, with moderator and timestamp); **Rename** sets a member's nickname (blank resets it); **Strip Roles** removes all of a member's roles after confirmation.

## 📜 Logger system

Logs server events to dedicated channels, one per category:

| Category | Logs |
|---|---|
| 📜 message | Message edits, deletes, bulk deletes (with original content) |
| 👥 member | Joins, leaves, kicks (detected via audit log), nickname/avatar changes, role adds/removes, voice joins/leaves/moves/mute/deafen |
| 🛠 server | Channel create/delete/rename/topic/slowmode, thread events, emoji create/delete/rename, role create/delete/update, invite create/delete |
| 🚨 moderation | Bans, unbans, timeouts, message clears, user data wipes (with moderator + reason from the audit log) |

Messages are cached in `data/message_log.db` so deletes show the original
content even when Discord doesn't provide it. Log channel config lives in the
same database (`guild_logs` table), set per guild per category.

| Command | Who can use it | What it does |
|---|---|---|
| `/setup_logs` | Administrator | Creates the 📜 Server Logs category + 4 log channels (staff-only) and wires them up |
| `/change_logchannel` | Administrator | Point one log category at a different channel |
| `/log_settings` | Everyone (no gate — anyone can view it) | Show which channels each category logs to + disabled events |
| `/log_toggle <category>` | Administrator | Enable/disable one event type (subcommands: message, member, voice, server, moderation) |

> **Note:** the Logger needs the **Message Content** privileged intent to log
> message text. It's enabled in `bot.py` (`intents.message_content = True`) —
> you must also toggle it on in the Discord Developer Portal under
> Bot → Privileged Gateway Intents.

## 📋 GitHub ban log

Bans and kicks can be logged to a GitHub Projects board as an off-Discord
backup — staff already work in that board, and it survives even if the
server or the bot's database is gone. Project items can't host image
uploads, so evidence is links (a screenshot attachment's Discord CDN link
embeds fine).

**Setup** — add to your `.env` (never commit it):
```
GITHUB_PROJECT_TOKEN=paste-a-classic-token-with-the-project-scope-here
GITHUB_PROJECT_OWNER=poos241
GITHUB_PROJECT_NUMBER=2
```
The token must be a **classic** personal access token with the `project`
scope — a fine-grained token without Projects access fails with
"Resource not accessible by personal access token". Classic tokens can't
be limited to one project, so treat the token like a password and use the
narrowest token you can. Point the bot at a test board first
(`GITHUB_PROJECT_OWNER` = your own username); go-live is just changing
the owner to the real board's owner plus a restart — never log test
entries to the real board.

| Command | What it does | Who can use it |
|---|---|---|
| `/testbanlog` | Posts a clearly-marked TEST item to prove the pipe works | Admins |
| `/banlog` | Logs a ban/kick: action, reason, member picker or user ID, optional Status/tags, evidence links, optional screenshot attachment | Manage Server / Admin |
| `/banlog_update` | Changes the Status/tags of the most recent logged case for a user, or appends a dated note | Manage Server / Admin |
| `/banlog_delete` | Removes the most recent logged case for a user (type `DELETE` to confirm) | Manage Server / Admin |

`/banlog` and the `/userinfo` panel's **Log to GitHub** button both show a
preview first (title, body, Status/Tags, and any cases already logged for
that user) with Post/Cancel buttons — nothing posts without the preview
step. Every item body carries the action, server, logger, date, reason,
evidence links, and the last 5 cases from the bot's own mod history.
Logged items are tracked locally (`ghlog_items` table) so updates and
deletes find the right board item, and update/delete refuse when the
board in `.env` doesn't match the board the item was logged to. Status
and tags are typed text with forgiving aliases ("trolls" →
"Trolls/Bullies"); a mismatch warns instead of failing. Full
auto-logging of every ban/kick is deliberately not built yet — logging
stays manual and previewed.

## Built-in commands (fun cog) — 🍽️ Eat It or Yeet It

A party voting game: the bot serves up a random food, everyone votes
**Eat it** or **Yeet it** with the buttons, and the verdict is announced
when the timer runs out. Rounds **survive bot restarts** — if the bot goes
down mid-round, the buttons keep working and anything that expired while it
was away gets tallied on startup.

Full options and gates for all six Eat It or Yeet It commands: see the [Complete command reference](#-complete-command-reference) above.

**Food sources** (`/eatyeet` option):
- **Auto (mix of API + local)** (default) — each round has a 90% chance of a
  live meal from [TheMealDB](https://www.themealdb.com) (free, no key needed),
  otherwise the local list. API foods show a 🌐 **fresh** rarity and the
  round embed displays the dish's real photo.
- **Local list only** — no internet: hand-written foods + community suggestions.
- **API only** — live meals only, no local fallback. If the API is
  unreachable, no round starts (you'll get a warning instead).

**Scoring** — vote with the majority to earn points: common = 1,
weird / fresh / community = 2, cursed = 3. Win streaks are tracked with a
best-streak record, and results name every voter on each side.

**Live countdown** — the round post shows a ticking timer with a progress
bar (▓▓▓▓▓▓░░░░) plus when voting ends. In the last 15 seconds it switches to
🔨 **HAMMER TIME!** and counts down to the verdict.

**Rematch** — when a round ends, the results post gets a 🔁 **Run it back**
button. Anyone can tap it to instantly start a new round with the same
duration and food source. It works even on old result posts after a restart.

Game data lives in SQLite (`eatyeet_stats`, `eatyeet_suggestions`,
`eatyeet_active`, and `eatyeet_rematch` tables; active rounds are what make
restarts safe). The old JSON files are kept as rollback copies.

## Built-in commands (level system)

A message-based XP system. Every message earns a random amount of XP in the
configured range (subject to a per-user cooldown). Level *n* requires
*n* × 100 XP, and leftover XP rolls over into the next level. All XP data
and settings are stored per server in the SQLite database.

Full options and gates for all nineteen level-system commands: see the [Complete command reference](#-complete-command-reference) above.

Voting in Eat It or Yeet It also earns level XP: 10 XP per vote, plus
10 × the game's majority points as a bonus (e.g. 20 XP for winning a
common round, 40 XP for a cursed one). Admins can turn this off with
`/toggle_game_xp`.

Extras: `/daily` gives a claimable XP bonus every 20 hours with streak
bonuses, `/xp_event` runs server-wide multiplier events (great for event
nights), and `/rank` generates a shareable rank card image. Channels like
bot-spam can be excluded from XP with `/toggle_no_xp`.

Level-ups post a confetti celebration card (with your `/cardcolor` accent
if you set one) alongside the announcement text — admins can customize
that text with `/set_levelup_message` using `{user}`, `{name}`, and
`{level}` placeholders (it falls back to the default message if unset).

## 👋 Introduction tracking

New members introduce themselves in a channel, and the bot tracks who
has and hasn't — then hands out a role to people who introduced
themselves. Think of it as a guest book: say hello in the intro
channel, get the role; delete your intro, lose the role (if auto-remove
is on).

| Command | What it does | Who can use it |
|---|---|---|
| `/intro_set_channel` | Set the introductions channel (and optional log channel) | Manage Server |
| `/intro_set_role` | Pick the role given for introducing (refuses @everyone, managed roles, and roles above the bot or you) | Manage Server |
| `/intro_settings` | Show the current intro setup | Manage Server |
| `/intro_toggle` | Turn auto-assign, auto-remove, and scan-on-message on/off | Manage Server |
| `/intro_scan` | Scan the intro channel's history for introductions (default 100, max 1000) | Manage Messages |
| `/intro_check` | Check whether a member has introduced themselves | Manage Messages |

There's also a **Check Introduction** right-click (context menu) command
on any member. The bot watches messages in the intro channel as they
arrive (when scan-on-message is on), re-assigns the role when a member
rejoins, clears the record when an intro message is deleted, and syncs
when the role is added or removed by hand. State lives in SQLite
(`introduction_status` + `introduction_config` tables, one row per
guild — multi-guild, unlike the original Little Haven bot this was
ported from). The original bot's custom module-permission system was
deliberately not ported; gates use Discord permissions.

## 📝 Modlog viewer + edit

Browse, recap, and fix moderation cases from the same mod history
behind `/userinfo` — no new store, no parallel data. All four commands
are ephemeral (only you see the results) and need **Manage Server** or
**Administrator**.

| Command | What it does | Who can use it |
|---|---|---|
| `/modlogs` | List cases, 5 per page with Prev/Next, filter by member/user ID, type, or before/after date (YYYY-MM-DD); guild-wide recent list caps at 250 | Manage Server / Admin |
| `/modlogs_recap` | Counts by type, warns/notes totals, most recent case, and active tempban status for a user | Manage Server / Admin |
| `/modlogs_edit` | Pick one of the 25 most recent cases, then edit its reason (old reason prefilled) or delete it with a full-case confirm | Manage Server / Admin |
| `/mod_actions` | Everything one moderator has done (matches by moderator ID, falls back to name) | Manage Server / Admin |

Cases are numbered per user, most-recent-first. Editing or deleting
re-checks the case at click time (it refuses cleanly if the case is
gone), and editing/deleting a warn mirrors into the matching warns
entry so panel counts stay right. Edit/delete actions are logged to
the Logger's moderation channel. Types cover the 10 action bases the
bot actually records: warn, timeout, untimeout, kick, ban, tempban,
unban, clear, strip_roles, wipe.

## ⏱️ Timeout tracker board + presets

A live board showing every active timeout and tempban in one place,
plus quick timeout lengths and the bot noticing hand-done timeouts.

| Command | What it does | Who can use it |
|---|---|---|
| `/timeout` | Time a member out, with a preset picker or a free-form duration | Manage Server / Admin |
| `/timeout_board` | Post the Active Timeouts board in a channel (run again in another channel to move it), show its status, or remove it | Manage Server / Admin |

**Presets** on `/timeout`: Light (5 minutes), Short (15 minutes),
Medium (1 hour), Long (1 day), Extended (1 week), Severe (2 weeks).
Free-form durations still work (`1h30m`, `2w4d`, bare numbers are
minutes, case-insensitive) with Discord's 28-day maximum enforced.
If you pick both a preset and a duration, the preset wins.

**The board** is one "⏱️ Active Timeouts" embed per guild: who, why,
who did it, and when it expires (soonest first), split into Timed
out / Tempbanned sections, capped at 25 entries with a "+N more"
line. It refreshes on every timeout change and every 5 minutes, and
re-posts itself if the message is deleted; if its channel is gone it
clears its config and logs it. It reads the existing mod records, so
currently-active tempbans show up too. Board config lives in the
`timeout_board_config` table.

**Replace instead of overwrite:** timing out someone who already has
an active timeout asks first — Replace timeout or Keep current
timeout — instead of silently swapping it. The same step appears in
the `/userinfo` panel's Timeout button.

**Hand-done timeouts:** if a mod times someone out (or lifts one) by
right-clicking in Discord instead of using the bot, the bot spots
it via the audit log, records it, and puts it on the board (or
clears it). It tells its own timeouts apart from hand-done ones, so
nothing is double-counted; if the audit log can't be read, the change
is still recorded with moderator "Unknown".

## 🌐 Web dashboard

A Flask web dashboard at `http://127.0.0.1:5000` by default. Log in with
Discord — server management pages need **Manage Server** /
**Administrator**, while profile, directory, feed, and friends pages are
open to any logged-in member. Every API route checks both login and
guild permission.

**Setup:** copy `.env.example` to `.env` and fill in `WEB_SECRET_KEY`,
`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DISCORD_REDIRECT_URI`
(the redirect URI must also be registered in the
[Discord Developer Portal](https://discord.com/developers/applications) under
OAuth2 → Redirects). The dashboard also needs `BRIDGE_SECRET` in the
same `.env` (see below).

**What it covers:** server overview, member/role/channel browsers, moderation
actions (timeout/kick/ban/unban — same safety checks as the `/userinfo` panel, and
each web mod action needs its own matching Discord permission: Ban Members to
ban, Kick Members to kick, Timeout Members to time out, Manage Messages to
warn/clear, and so on; wiping a member's data needs the admin tier plus the
member's user ID re-typed as confirmation),
a searchable log-event history (the Logger records every event to a
queryable table for this, with a CSV export), user profiles, the member
directory, the community activity feed, friends, a live voice-channel
viewer, and backups.

### Bot + website: two separate processes (November 2026)

The bot and the website used to run in one process (the website as a
background thread inside the bot). Since November 2026 they are **two
separate processes**, each with its own auto-restart watchdog — if one
goes down, the other keeps running, and a crash restarts only the side
that crashed.

**How they talk:** the bot exposes a small bridge API on
`http://127.0.0.1:5001` (localhost only, never reachable from outside
the machine). The website is a plain Flask app that calls the bridge
for all live Discord data and actions — member/channel/role lists,
voice states, and moderation actions (timeout, kick, ban, unban,
rename, strip-roles, purge, DM, XP). Every bridge call has a timeout
and degrades to a clear "bot unavailable" (503) page instead of
hanging. The bot stays the single Discord connection; the website
never logs in to Discord itself, and the bot token never enters the
website process. Pure database reads (levels, profiles, activity feed,
log history) run on the website's own async loop instead of the
bridge.

**The bridge secret:** both sides read the same `.env`. The bridge
only starts when `BRIDGE_SECRET` is set to a long random string both
sides share; every bridge request carries it as an `X-Bridge-Secret`
header, and a wrong or missing secret gets a 401. If the secret is
missing, the bot logs `[ERROR] Bridge API will NOT start` and keeps
running — the website just shows "bot unavailable" on live pages
until you add the secret and restart the bot. Optional:
`BRIDGE_PORT=5001` changes the port (default `5001`);
`BRIDGE_ENABLED=0` turns the bridge off entirely.

**Starting them:** double-click `run_bot.bat` (bot under its
watchdog) and `run_web.bat` (website under its watchdog), or run
`python bot.py` and `python run_web.py` in separate terminals. The
order doesn't matter — each side tolerates the other being down. The
watchdogs (`watchdog.py`) relaunch their side only on a crash (exit
code 1) or an explicit restart request (exit code 42, e.g. from
`/restart_bot`); a clean stop (exit 0, e.g. `/shutdown_bot`) stays
stopped; any other exit code logs loudly and stops; more than 5
restarts in 60 seconds trips a burst guard that stops loudly instead
of looping forever. A website crash never restarts the bot and vice
versa. On Windows each child runs in its own process group, so
Ctrl+C in a console stops only that watchdog cleanly.

**What you see:** with both up, the dashboard works exactly as
before. With the bot down, live pages and actions show "bot
unavailable" while the landing page and database-backed pages keep
working. If the website is down, the bot and its commands are
unaffected. After updating dashboard files, restart the website
process (`run_web.bat`) so the app rebuilds with the current routes —
reloading a page alone is not enough.

## Adding a new cog

> Working on the code itself? Read the **[Bot Developer Handbook](https://poos241.github.io/Discord-Testing-Bot-Grounds-V1/)**
> — architecture, patterns, and examples with sidebar navigation and search
> (source pages in `website/docs/`).

Cogs are how you add features. Each cog is one Python file in the `cogs/`
folder containing a class and a `setup` function:

1. Create `cogs/my_cog.py`:

```python
import discord
from discord.ext import commands

class MyCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(name="hello", description="Say hello")
    async def hello(self, ctx: discord.ApplicationContext):
        await ctx.respond("Hello!")

def setup(bot):
    bot.add_cog(MyCog(bot))
```

2. Add `"cogs.my_cog"` to the `COGS` list at the top of `bot.py`.
3. Restart the bot — your new slash command will sync on startup.

## 🐛 Debug mode

A shared debug system for the bot and the web dashboard. Off by default.

**Enable at startup** — add to your `.env`:
```
DEBUG=1
```

**Toggle at runtime** (no restart needed):
- Discord: `/debug on` · `/debug off` · `/debug status` (Manage Server permission required)
- Web dashboard: click the 🐛 button (bottom-right, appears when logged in) to open
  the debug panel, then hit **Enable Debug** / **Disable Debug**

The runtime toggle is saved to `data/.debug_enabled` and persists across restarts
until you change it again. Delete that file to go back to the `.env` setting.

**What you get when it's on:**
- Bot console + `data/debug.log`: every slash command logged (who ran it, where,
  with what options), plus full tracebacks on command errors
- Web console + `data/web_debug.log`: every HTTP request in Flask dev-server style
  (`192.168.1.129 - - [21/Oct/2026 16:29:46] "GET /servers HTTP/1.1" 200 -`)
  with response time — replaces the request logging lost when switching to waitress
- Web debug panel (🐛 button): enable/disable toggle, recent API requests with
  timing, server log viewer (last 40 lines of `web_debug.log`), plus any
  JavaScript errors captured on the current page

## 🔐 Web dashboard permissions

The site has a public front and gated dashboard areas:

- **Public** — the landing page at `/` needs no login. It describes the
  bot, its features, and how to get started.
- **Gated** — the server list, server pages, and APIs need a Discord login
  plus the right tier (see below). Nav links only appear when you can
  actually use them.

External links in the nav bar:

- **GitHub** (public) — the bot's repo.
- **Handbook** (public) — the Bot Developer Handbook.
- **Staff Handbook** (moderator+) — only shown to users with moderator
  permissions in at least one server. The landing page also has a
  Resources section with the two public links.

### 👤 User profiles

The profile page (`/profile`) is a customizable end-user page. Layout follows the Steam profile pattern: a header with avatar, name, and status plus a level badge and member-since on the right, a main column (recent activity, stats) and a sidebar (featured, badges, servers), stacking to one column on narrow screens. Visual treatment is Steam-like too: translucent panels over the background art with dark-blue gradient section header bars, a background fade/vignette so content pops, an accent-framed avatar, a badge shelf with an earned-count header, hover lifts on cards, and a level progress ring around the level number (the ring fills with XP progress toward the next level). Cleanup round: XP progress bars use the user's accent color, stat cells sit in a symmetric 3x2 grid with small-caps labels, activity times read as relative times ("2h ago"), panels are slightly more opaque for readability over busy custom backgrounds, and the own page has a Copy button for the public profile link. Ideas round: the customize form live-previews bio/status/name/pronouns/tags/avatar/background as you type, the Badges section shows a 'Next up' teaser with progress toward the closest unearned badge, section header bars tint with the user's accent color, the save button briefly flips to 'Saved!', the customize form shows a profile completion meter, and hovering the level ring shows XP to the next level. Editing moved to its own page (/profile/edit): the profile header has an Edit profile button, the edit page shows a live preview card above the form, social links are now an add-up-to-10 list with a + Add link button that auto-detects each site and shows its icon, and every field has a ? help button (hover or tap) with a plain-language explanation of what goes there. Backgrounds can also be uploaded from the user's PC (Upload image on the edit page, max 5 MB, PNG/JPG/GIF/WebP, stored under web/static/uploads/backgrounds/ and never committed); backgrounds now preload so a dead link hides the dark overlay instead of leaving a veil, and the level ring sits below the banner. A notification bell in the navbar shows mod cases filed against the user plus level-ups, with an unread badge, per-item dismiss and mark read/unread, and Clear read / Clear all. Profiles can opt in to showing color-coded roles from one picked server (toggle + server picker on the edit page), on the own and public pages. Roles can show either at the bottom of the profile or on the bio card at the top (a placement picker on the edit page; bottom is the default). An opt-in local-info block on the bio card shows where the user is from (country plus a broad area only, picked from a grouped world-places list — never a city or town, so it stays private), the local time in their time zone with the zone name, and a flag from an optional country picker; the time refreshes every 30 seconds. A DM status (not set, open, closed, ask first) shows on the bio card with a green, red, or yellow dot. Time zone, place, and country are stripped from public profiles unless the owner turned the display on. New profile fields land in the profiles table automatically: the bot adds missing columns to an existing database on boot. Profile settings live in the bot's SQLite database (`bot.db` at the bot folder root, `profiles` table) — migrated from the old `data/profiles.json` on first read, with the JSON kept as a `profiles.json.migrated` backup. The API is `GET/POST /api/profile` (login + CSRF), `GET /api/profile/stats` (login), and `GET /api/profile/public/<user-id>` (public), plus `GET /api/profile/roles?guild_id=` (login, membership-checked) for the roles display.

**Customization** — bio (500 chars), accent color (picker + 8 swatches) tinting the banner and save button, status message, social links (Twitch, YouTube, Twitter/X, website), pronouns, and a custom display name (falls back to the Discord name). Interest tags (comma-separated, up to 10) render as chips.

**Pictures** — custom profile picture URL and banner image URL. By default both fall back to Discord: the Discord avatar, and the Discord banner (stored in the login session from `/users/@me`; animated banners use the `.gif` URL). If no Discord banner exists, the accent color shows. A custom background image URL renders behind the whole profile page (with a dark overlay for readability).

**Bot stats** — live stats pulled from the bot: level, total XP, daily streak, games played, game points, and majority votes, with a per-server breakdown (level, XP, rank, games, points, join date). A progress bar shows XP toward the next level (each level needs `level × 100` XP). Stats aggregate across every server the bot is in where the user has level data. "Member since" shows the earliest server join date.

**Achievements** — badges derived from stats: Level 5/10/25/50, First Game, Regular Player (25 rounds), Century Club (100 points), 7-Day Streak, and Crowd Favorite (10 majority votes). Earned badges are highlighted; unearned ones show dimmed on your own profile. A featured badge and a featured stat can be pinned to a showcase section.

**Recent activity** — a feed of the last 20 events, logged going forward by the bot: level-ups and daily claims (Level system cog) and Eat It or Yeet It rounds played (`profile_activity` table, unix timestamps).

**Public profiles** — users can opt in with "Make my profile public" to get a shareable link (`/profile/<user-id>`) anyone can view without logging in. Public profiles show bio, status, socials, tags, stats totals, best-level progress, member since, earned badges, featured items, and activity only — per-server details are never shown publicly (guild names would reveal membership). Public profiles are off by default; private profiles show a locked message to visitors.

The profile page also lists the user's servers (from `/api/servers`, with access-level badges) linking to each dashboard/basic page.

## 🆕 Building-mode batch — October 2026

Eighteen systems and fixes built in one batch (developed locally on the bot
host, pushed together). Most bot commands below are guild-scoped slash commands; 18 are global (all nine WatchList commands, eight admin-cog commands, and `/xp_event`) — see the Scope column in the [Complete command reference](#-complete-command-reference); web pages live on the dashboard.

**Notifications: clear everything + improvements** — the bell now has
All/Mod/Level-ups filter tabs, per-item dismiss (×) and mark read/unread,
plus footer buttons Clear read and Clear all (Clear all asks for
confirmation). Dismissals are stored per user so Mark all read no longer
wipes them; the badge counts unread among the newest 30.

**Question of the Day (QOTD)** — `/qotd today|history|submit|post|skip|
config|pending|approve|reject|remove`. One safe-for-work question a day
(default 09:00, configurable channel/time/timezone) with a 24-hour
auto-archive discussion thread, 60 seed questions, no repeats until the
pool is exhausted, and missed-day catch-up. Mod gate: Manage Messages.
Requires the `tzdata` package (in `requirements.txt`) for timezone names.

**Ticket system** — `/ticket panel|config|show|open|close|reopen|claim|
delete|add|remove|list`. A panel button + topic modal opens one ticket
per user with per-server numbering; closing locks, renames, and logs the
ticket while leaving Reopen/Delete buttons. Staff is the configured role,
or Manage Messages/Administrator as fallback.

**Unified backup + restore** — `/backup now|status` plus a daily 04:00
snapshot, and a mod-only `/backups` web page (manual snapshot, download,
delete, restore). Each snapshot zips `bot.db` + `message_log.db` (via the
SQLite backup API, safe while running) + JSON state + a manifest with
SHA-256 hashes. Retention: newest 14 daily + 10 manual/pre-restore.
Restore verifies hashes, takes a pre-restore safety snapshot first, then
replaces data — restart afterward. Warning: restore overwrites live data,
so don't test it casually.

**Appeals + mod notes search** — `/appeal submit|list|review` (approve
lifts a ban/timeout, deny records a reason, both DM the appellant) and
`/modnotes search <keyword> [user]` across mod notes/warns/cases.
Ban/timeout DMs now mention appeals. Review buttons are non-persistent:
re-run `/appeal review` after a restart.

**JSON → SQLite migration (finished)** — mod cases, watch list, and Eat It
or Yeet It stats/suggestions/active rounds/rematch now live in SQLite
(`utils/json_sqlite_store.py`) instead of JSON files. Migration is lazy:
the first load after restart imports the JSON, and the originals stay
untouched as rollback. Profiles migrated earlier the same way.

**Back-to-top fix** — the back-to-top button moved from bottom-right to
bottom-left so it no longer overlaps the debug (🐛) button.

**Friend system (web)** — send/accept friend requests, unfriend, and add
by user ID. Your own profile has a Friends section linking to friends'
profiles; public profiles show only friends who are themselves public.
An opt-out toggle blocks new requests and auto-declines pending incoming
ones. Friend requests also appear in the notification bell.

**Voice time XP** — `/voicexp optin|optout|status|leaderboard` plus admin
`config|setrate|setcap|enable|disable`. Opted-in members earn 1 XP per
qualifying minute in voice (not alone, not muted/deafened, not AFK),
banked in 5-minute chunks, with a 100 base XP/day cap (UTC day, event
multipliers apply on top). Stage channels are excluded; the leaderboard
is Discord-only. Hotfix 2026-10-28: `/voicexp optin` crashed on first use
because the user-row saver passed explicit `NULL`s for missing columns;
the saver now drops `NULL`s before applying defaults (same fix applied
to the lockdown and auto-thread savers).

**Lockdown + slowmode** — `/lockdown lock|unlock|lockall|unlockall|
slowmode|status`, gated to Manage Channels. Locking denies @everyone
send_messages and records the previous overwrite so unlocking restores it
exactly; timed locks persist across restarts via a 1-minute auto-unlock
ticker. `lockall` skips already-locked and forum channels. Slowmode
0–21600 seconds (0 clears).

**Automod basics** — `/automod status|toggle|config`, with the same
toggles on the Logger settings page. Four rules, all default OFF: spam
bursts (5 messages in 10s), invite links (own vanity code allowed),
external links, and all-caps (10+ letters, 80%+ uppercase). Hits delete
the message and log to the Logger; Manage Messages members are exempt,
and log embeds throttle to one per member per rule per 60 seconds.

**Auto-threads** — `/auto_thread`, `/set_auto_thread_channel` (archive
60/1440/4320/10080 minutes + name prefix), `/remove_auto_thread_channel`, `/auto_thread_status`, gated
to Manage Channels. Every message in a designated channel gets a
discussion thread named prefix + first 80 characters; bots, webhooks,
threads, replies, and `!` commands are skipped, and archive falls back
to 24h if the server boost level rejects the chosen duration.

**Live VC viewer (web)** — `/servers/<id>/voice` (moderator-gated) shows
who is in which voice channel right now from the bot's live cache,
refreshing every 15 seconds (pauses when the tab is hidden) with a
manual Refresh button. Join links open the channel in Discord. Linked
from the Channels page sidebar.

**`/time`** — `/time [user]` (blank = yourself) shows that user's local
time from their profile timezone, formatted with zoneinfo. No timezone
set: you get a nudge to set one, others show "not set", bots show "no
profile". Another user's time only shows if they opted in to show local
info (same rule as the web bio line).

**Mod-awardable custom badges** — `/badge create|award|remove|delete|
list`, gated to Manage Messages. Mods create badges (per-server-unique
slug, icon defaults to 🏅) and award them; awarded badges render on the
badge shelf (own + public, counted in "Badges N") and log to the
recipient's activity feed. The public API returns icon/name/description
only, so no server membership leaks. Custom badges can't be featured
yet, have no expiry, and custom-emoji icons show as raw text on the web
shelf.

**Logger export (repaired)** — the Logger History page's Export CSV
button now writes real columns (`id, guild_id, timestamp, category,
event_type, summary`) with a UTF-8 BOM for Excel and a `-user-<id>`
filename suffix when filtered, and it respects the user/channel/date
filters. Logger now records rich summaries (description + author + field
lines, 2000 chars) so per-user export works for events logged after
restart; older rows have NULL summaries and can't match user/channel
filters. Exports cap at 5000 rows.

**Member directory (web)** — `/directory` (login-gated) browses members
by interest tag: a tag cloud with counts, AND filtering on multiple
tags, and search across name/bio/status/tags. Only public profiles
appear, under the same privacy rules as public profile pages. Global,
not per-server.

**Community activity feed (web)** — `/feed` (login-gated) shows
level-ups, daily claims, Eat It or Yeet It rounds, and badge awards,
newest first, 30 per page with a Newer/Older pager and a kind filter.
Only public-profile users appear, entries link to `/profile/<id>`, and
guild IDs are stripped from API responses. Manual Refresh only.

## 🔍 Security audit — October 2026

A full read-only scan of the bot and dashboard (52 findings) landed as
fixes in October 2026 — all local-first, each batch verified with a
harness on the bot host before any restart:

- **Access control** — the member list/detail API routes and the backup
  download/restore routes were open to any logged-in user (or a moderator
  of an unrelated server). Both now require the moderator tier on a guild
  the bot is actually in. The debug APIs and the debug panel are staff-only
  the same way (and fail closed while the bot is down); the events summary
  needs a guild ID plus the moderator tier; the server list only ever
  returns servers the caller is a member of.
- **Per-action permissions** — web mod actions used to share one coarse
  moderator tier, so a mod who could warn could also ban. Each action now
  needs its own Discord permission bit (see above), and wiping a member's
  data needs the admin tier plus the user ID re-typed.
- **Data safety** — a failed database read could silently roll a live
  table back to its pre-migration JSON; loads now retry locked-database
  errors and refuse the stale fallback once migrated. Concurrent ticket
  opens could share a number; numbers are now claimed under a per-guild
  lock before the channel is created.
- **Reliability** — one broken cog no longer kills startup, a slash-command
  sync failure no longer kills the web dashboard or status rotation, the
  Eat It or Yeet It expiry loop and the QOTD scheduler survive one bad
  round/guild, a failed tempban unban stays queued instead of being
  recorded as a success, and `/clear_user` errors reply properly.
  The status rotation itself survived a live crash (gateway reset while
  the PC slept) — it now skips the write while disconnected, catches
  connection errors per tick, and `on_ready` starts it exactly once.
- **Privacy** — public profiles no longer leak a guild name, and the
  members-page mod buttons send the CSRF token they were missing
  (they used to fail every time).

## 🔍 Security audit — November 2026 (readiness scan)

Ahead of deploying in a server with 1700+ members, a second full
read-only scan landed on 2026-11-02 — 100 findings (P0 2, P1 22,
P2 41, P3 35). The two must-fix items were fixed the same day:

- **Server-home exposure (P0)** — the server-home page and its
  status API were login-only, so any logged-in Discord user could
  read host load, CPU temperature, RAM, disk, service up/down, bot
  guild/member counts, and AdGuard + Portainer numbers. Both routes
  now require the admin tier (same helper as the restart route) and
  fail closed while the bot is down.
- **Watchlist wipe (P0)** — the watchlist loader swallowed any load
  error and returned empty, so the next watch save would silently
  overwrite the whole live watchlist table with just the new change
  (the October wipe pattern, one layer up). It now fails closed: a
  load failure marks the store unusable, commands report
  "temporarily unavailable — nothing was changed" instead of
  operating on empty data, saves refuse while unusable, and the
  store heals itself on the next successful reload.

The four named P2s from October were also fixed in November:

- **Startup double-start** — the status loop was already guarded; the
  unguarded part was the web dashboard thread restarting on every
  reconnect (a second waitress failing to bind the port). Now a
  `_web_started` flag skips it on re-runs (and a failed start retries
  next time instead of being skipped forever). Superseded by the
  split below: the bot no longer starts the website in-process at all.
- **Lockdown auto-unlock** — the sweep had per-row gaps, so one
  database error mid-sweep killed the loop and timed locks never
  expired until restart. Every row is now wrapped: a failure logs
  loudly, the sweep continues, and the failed row stays queued and
  retries next tick.
- **Upload cap** — Flask's limit was 2 MB while the site advertised
  5 MB, so 2–5 MB background uploads died with a generic 413. The
  enforced cap is now 5 MB to match (over 5 MB is still refused with
  the proper message).
- **Swallowed profile-migration failure** — a failed profile-columns
  migration printed one quiet line and booted on a stale schema. It
  now logs a loud `[DB] ERROR` with the full traceback, records
  `PROFILE_MIGRATION_ERROR`, and `/api/debug/bot-status` surfaces it
  as `profile_migration_error` (null when healthy). It deliberately
  does not kill the whole bot over a profiles-table issue.

**Heartbeat fix (November 2026)** — the timeout board's 1-minute
refresh did a synchronous database read on the Discord event loop
while asking for a write lock, and the website thread held that lock
— the loop stalled and Discord warned the heartbeat was blocked for
10, then 20 seconds. Two fixes: database reads now use a read-only
path that never takes a write lock, and the board's database loads
run in a background thread, so a slow read can no longer freeze the
bot. Proven with a test that holds the write lock while a read runs:
the read returns at once.


## Troubleshooting

- **`Improper token has been passed`** — your `.env` file is missing or
  `TOKEN2=` doesn't match your token. Make sure the file is named exactly
  `.env` and sits next to `bot.py`.
- **Slash commands don't show up** — wait a few minutes after the first
  start; also confirm you invited the bot with the `applications.commands`
  scope.
- **Bot can't see members / crashes on startup** — the **Server Members,
  Message Content, and Presence Intents** must be enabled in the Developer
  Portal (Bot tab, Privileged Gateway Intents), then restart the bot.
- **Dashboard pages error after updating files (e.g. a BuildError for a
  new page)** — the running website process predates the new code.
  Restart the website process (`run_web.bat`, or stop and re-run
  `python run_web.py`) so the app rebuilds with the current routes;
  reloading a page alone is not enough. The bot does not need to
  restart for dashboard-only changes.
- **Website shows "bot unavailable" on live pages** — the bridge isn't
  up. Check the bot's console: if it says `[ERROR] Bridge API will NOT
  start: BRIDGE_SECRET is not set`, add `BRIDGE_SECRET=<a long random
  secret>` to `.env` (same file as your token) and restart the bot.
  If the bridge is listening but pages still 503, make sure the
  website process is running and can reach `127.0.0.1:5001`.
- **Bot or website keeps restarting in a loop** — the watchdog gives
  up loudly after more than 5 restarts in 60 seconds (burst guard).
  Read the last `[ERROR]` lines in that console: they name the crash.
  Fix the cause, then start it again with `run_bot.bat` /
  `run_web.bat`.
- **`/shutdown_bot` says you're not authorized** — your user ID isn't in
  `OWNER_IDS` in `config.py`.
- **`pip install` fails on `databases`** — make sure you're on Python 3.10+
  and pip is up to date (`pip install --upgrade pip`).
