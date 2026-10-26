# Discord Bot Template (Python)

A starter template for building a Discord bot in Python. It's built on
**pycord**, uses slash commands, and organizes features into **cogs** so you
can add new ones without touching the core files.

**What it comes with out of the box:**
- Slash commands that sync automatically on startup
- Admin cog: user info, clearing a user's messages, adding/removing roles,
  renaming the bot or users, and owner-only shutdown/restart commands
- A rotating bot status (cycles through messages every 10–60 seconds)
- SQLite database layer (SQLAlchemy + `databases`) with ready-made tables for
  welcome messages, levels/XP, tickets, threads, and voice-channel maps
- JSON helper functions for simple per-guild config files
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
   **Server Members Intent**.
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

### 6. (Optional) Edit `config.py` for your server

- `OWNER_IDS` — put your Discord user ID(s) here. Required for
  `/shutdown_bot` and `/restart_bot`. (Right-click yourself in Discord →
  Copy User ID; enable Developer Mode first if you don't see it.)
- `GUILD_IDS` — your test server ID(s).
- `statuses` — the list of messages the bot cycles through as its status.

### 7. Run the bot

```bash
python bot.py
```

You should see `✅ Logged in as YourBot#1234 ... Commands synced!` in the
console. The SQLite database (`data/bot.db`) is created automatically on
first run. Slash commands can take a few minutes to appear in Discord the
very first time.

---

## Project structure

```
Discord Bot Templet Mde With Python/
├── bot.py                  # Entry point: loads token, intents, and cogs
├── config.py               # Server/user IDs, responses, permission checks, JSON helpers
├── requirements.txt        # Python dependencies (incl. Flask for the web dashboard)
├── .env                    # Your bot token + web dashboard secrets (you create this — never commit it)
├── web/                    # Web dashboard (Flask, see section below)
├── cogs/
│   ├── admin_cog.py        # Admin slash commands (see table below)
│   ├── fun_cog.py          # Eat It or Yeet It party game (see section below)
│   ├── Level_system.py     # Message XP, levels, leaderboard (see section below)
│   ├── WatchList.py        # Watch List system: log watched users' messages (see section below)
│   └── Logger/             # Server event logging (see section below)
│       ├── __init__.py     # Registers all Logger cogs
│       ├── config.py       # Log categories, colors, channel names
│       ├── database.py     # SQLite: message cache + log channel config
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
├── data/
│   ├── eatyeet_*.json      # Eat It or Yeet It stats, suggestions, active rounds
│   ├── watchlist_data.json # Watch List: watched users per server
│   ├── mod_data.json       # /userinfo panel: warns, notes, case history, tempbans per server
│   ├── message_log.db      # Logger: cached messages + log channel config
│   └── DB/
│       ├── db.py           # Database connection (SQLite)
│       ├── models.py       # Table definitions
│       └── Storage/
│           └── storage.py  # Async get/save helpers for each table
└── utils/
    └── data_utils.py       # Simple JSON load/save helpers
```

## Built-in commands (admin cog)

| Command           | What it does                                        | Who can use it |
|-------------------|-----------------------------------------------------|----------------|
| `/userinfo`       | Self-updating mini mod panel: user card + Warn/Timeout/Kick/Ban/Clear/Notes/Watch/Add-XP/Remove-XP/Wipe-Data/History/Rename/Strip-Roles buttons (Ban/Timeout/Watch flip to Unban/Remove-timeout/Unwatch when active); Ban supports tempbans with auto-unban; Warn/Timeout/Kick/Ban show a confirm step with a DM on/off toggle; every action is recorded to case history; `test_mode` simulation toggle, `private` visibility toggle | Admins |
| `/clear_user`     | Deletes a user's messages in one or all channels    | Admins         |
| `/add_user_role`  | Gives a role to a user                              | Admins         |
| `/remove_user_role` | Removes a role from a user                        | Admins         |
| `/rename_bot`     | Changes the bot's nickname in the server            | Admins         |
| `/rename_user`    | Changes a user's nickname                           | Admins         |
| `/reset_user_name`| Clears a user's nickname                            | Admins         |
| `/shutdown_bot`   | Shuts the bot down                                  | Bot owners only|
| `/restart_bot`    | Restarts the bot                                    | Bot owners only|

## 👁️ Watch List system

Moderators can put users on a per-server watch list — every message a
watched user sends is mirrored to a configured log channel (with author,
channel, timestamps, content, attachments, stickers, and a jump link).
State lives in `data/watchlist_data.json`. All commands need **Manage
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
| `/log_settings` | Everyone | Show which channels each category logs to + disabled events |
| `/log_toggle <category>` | Administrator | Enable/disable one event type (subcommands: message, member, voice, server, moderation) |

> **Note:** the Logger needs the **Message Content** privileged intent to log
> message text. It's enabled in `bot.py` (`intents.message_content = True`) —
> you must also toggle it on in the Discord Developer Portal under
> Bot → Privileged Gateway Intents.

## Built-in commands (fun cog) — 🍽️ Eat It or Yeet It

A party voting game: the bot serves up a random food, everyone votes
**Eat it** or **Yeet it** with the buttons, and the verdict is announced
when the timer runs out. Rounds **survive bot restarts** — if the bot goes
down mid-round, the buttons keep working and anything that expired while it
was away gets tallied on startup.

| Command | What it does | Who can use it |
|---|---|---|
| `/eatyeet` | Starts a round. Pick a duration (30s test, 1/2/4/8/12/24h) and a food source (see below) | Everyone |
| `/eatyeet_end` | Ends the current round in the channel early | Starter or admins |
| `/eatyeet_leaderboard` | Top 10 players by points | Everyone |
| `/eatyeet_stats` | Your (or another member's) rounds, points, majority %, streaks | Everyone |
| `/eatyeet_suggest` | Suggest a food for the community pool (credited by name) | Everyone |
| `/eatyeet_history` | Last 10 finished rounds and their verdicts | Everyone |

**Food sources** (`/eatyeet` option):
- **Auto (mix of API + local)** (default) — each round has a 45% chance of a
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

Game data is stored in `data/eatyeet_stats.json`,
`data/eatyeet_suggestions.json`, and `data/eatyeet_active.json`
(active rounds — this is what makes restarts safe).

## Built-in commands (level system)

A message-based XP system. Every message earns a random amount of XP in the
configured range (subject to a per-user cooldown). Level *n* requires
*n* × 100 XP, and leftover XP rolls over into the next level. All XP data
and settings are stored per server in the SQLite database.

| Command | What it does | Who can use it |
|---|---|---|
| `/level` | Shows your (or another member's) level and XP progress bar | Everyone |
| `/leaderboard` | Top 10 users by level and XP | Everyone |
| `/getxpsettings` | Shows the server's XP rate, cooldown, level-up channel/message, role rewards, game XP | Everyone |
| `/set_xp_rate` | Sets the XP range earned per message (e.g. 1–5) | Admins |
| `/set_cooldown` | Seconds between XP gains per user (0 = off) | Admins |
| `/set_level_channel` | Sets the channel for level-up announcements (defaults to current channel) | Admins |
| `/set_level_role` | Awards a role when members reach a level (cumulative) | Admins |
| `/remove_level_role` | Removes a level's role reward | Admins |
| `/toggle_game_xp` | Toggles level XP earned by voting in Eat It or Yeet It (on by default) | Admins |
| `/toggle_no_xp` | Toggles message XP on/off for a channel (e.g. bot-spam) | Admins |
| `/xp_event` | Starts a server-wide XP multiplier event (2–5x, up to 24h) | Admins |
| `/xp_event_end` | Ends the XP event early | Admins |
| `/daily` | Claims daily XP bonus (streaks earn more, every 20h) | Everyone |
| `/rank` | Shows a rank card image with level, XP bar, and server rank | Everyone |
| `/cardcolor` | Sets your rank/level-up card accent color (hex, preset, or reset) | Everyone |
| `/set_levelup_message` | Sets a custom level-up announcement ({user}, {name}, {level}); blank resets | Admins |
| `/add_xp` | Grants XP to a user (level-ups are announced) | Admins |
| `/resetxp` | Resets a user's XP and level | Admins |
| `/cleardata` | Wipes all level data for the server | Admins |

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

## 🌐 Web dashboard

A Flask web dashboard runs alongside the bot (same process, background thread) at
`http://127.0.0.1:5000` by default. Log in with Discord — only members with
**Manage Server** / **Administrator** can use it, and every API route checks
both login and guild permission.

**Setup:** copy `.env.example` to `.env` and fill in `WEB_SECRET_KEY`,
`DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET`, and `DISCORD_REDIRECT_URI`
(the redirect URI must also be registered in the
[Discord Developer Portal](https://discord.com/developers/applications) under
OAuth2 → Redirects). Set `WEB_ENABLED=false` to run the bot without the dashboard.

**What it covers:** server overview, member/role/channel browsers, moderation
actions (timeout/kick/ban/unban — same safety checks as the `/userinfo` panel),
and a searchable log-event history (the Logger records every event to a
queryable table for this). Discord write actions from the dashboard are
scheduled onto the bot's event loop, so they're safe from the web thread.

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

The profile page (`/profile`) is a customizable end-user page. Layout follows the Steam profile pattern: a header with avatar, name, and status plus a level badge and member-since on the right, a main column (recent activity, stats) and a sidebar (featured, badges, servers), stacking to one column on narrow screens. Profile settings live in the bot's SQLite database (`data/bot.db`, `profiles` table) — migrated from the old `data/profiles.json` on first read, with the JSON kept as a `profiles.json.migrated` backup. The API is `GET/POST /api/profile` (login + CSRF), `GET /api/profile/stats` (login), and `GET /api/profile/public/<user-id>` (public).

**Customization** — bio (500 chars), accent color (picker + 8 swatches) tinting the banner and save button, status message, social links (Twitch, YouTube, Twitter/X, website), pronouns, and a custom display name (falls back to the Discord name). Interest tags (comma-separated, up to 10) render as chips.

**Pictures** — custom profile picture URL and banner image URL. By default both fall back to Discord: the Discord avatar, and the Discord banner (stored in the login session from `/users/@me`; animated banners use the `.gif` URL). If no Discord banner exists, the accent color shows. A custom background image URL renders behind the whole profile page (with a dark overlay for readability).

**Bot stats** — live stats pulled from the bot: level, total XP, daily streak, games played, game points, and majority votes, with a per-server breakdown (level, XP, rank, games, points, join date). A progress bar shows XP toward the next level (each level needs `level × 100` XP). Stats aggregate across every server the bot is in where the user has level data. "Member since" shows the earliest server join date.

**Achievements** — badges derived from stats: Level 5/10/25/50, First Game, Regular Player (25 rounds), Century Club (100 points), 7-Day Streak, and Crowd Favorite (10 majority votes). Earned badges are highlighted; unearned ones show dimmed on your own profile. A featured badge and a featured stat can be pinned to a showcase section.

**Recent activity** — a feed of the last 20 events, logged going forward by the bot: level-ups and daily claims (Level system cog) and Eat It or Yeet It rounds played (`profile_activity` table, unix timestamps).

**Public profiles** — users can opt in with "Make my profile public" to get a shareable link (`/profile/<user-id>`) anyone can view without logging in. Public profiles show bio, status, socials, tags, stats totals, best-level progress, member since, earned badges, featured items, and activity only — per-server details are never shown publicly (guild names would reveal membership). Public profiles are off by default; private profiles show a locked message to visitors.

The profile page also lists the user's servers (from `/api/servers`, with access-level badges) linking to each dashboard/basic page.

## Troubleshooting

- **`Improper token has been passed`** — your `.env` file is missing or
  `TOKEN2=` doesn't match your token. Make sure the file is named exactly
  `.env` and sits next to `bot.py`.
- **Slash commands don't show up** — wait a few minutes after the first
  start; also confirm you invited the bot with the `applications.commands`
  scope.
- **Bot can't see members / crashes on startup** — the **Server Members
  Intent** must be enabled in the Developer Portal (Bot tab, Privileged
  Gateway Intents), then restart the bot.
- **`/shutdown_bot` says you're not authorized** — your user ID isn't in
  `OWNER_IDS` in `config.py`.
- **`pip install` fails on `databases`** — make sure you're on Python 3.10+
  and pip is up to date (`pip install --upgrade pip`).
