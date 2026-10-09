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

### 4. Create your bot in the Discord Developer Portal

1. Go to the [Developer Portal](https://discord.com/developers/applications)
   and click **New Application** — give it a name.
2. Open the **Bot** tab, click **Reset Token**, and copy the token.
   **Keep this secret — never share it or commit it to GitHub.**
3. In the **Bot** tab, under *Privileged Gateway Intents*, turn on
   **Server Members Intent** and **Message Content Intent**.
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
├── requirements.txt        # Python dependencies
├── .env                    # Your bot token (you create this — never commit it)
├── cogs/
│   └── admin_cog.py        # Admin slash commands (see table below)
├── data/
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
| `/userinfo`       | Shows an embed with info about a user               | Admins         |
| `/clear_user`     | Deletes a user's messages in one or all channels    | Admins         |
| `/add_user_role`  | Gives a role to a user                              | Admins         |
| `/remove_user_role` | Removes a role from a user                        | Admins         |
| `/rename_bot`     | Changes the bot's nickname in the server            | Admins         |
| `/rename_user`    | Changes a user's nickname                           | Admins         |
| `/reset_user_name`| Clears a user's nickname                            | Admins         |
| `/shutdown_bot`   | Shuts the bot down                                  | Bot owners only|
| `/restart_bot`    | Restarts the bot                                    | Bot owners only|

## Adding a new cog

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

## Troubleshooting

- **`Improper token has been passed`** — your `.env` file is missing or
  `TOKEN2=` doesn't match your token. Make sure the file is named exactly
  `.env` and sits next to `bot.py`.
- **Slash commands don't show up** — wait a few minutes after the first
  start; also confirm you invited the bot with the `applications.commands`
  scope.
- **Bot can't see members / crashes on startup** — the privileged intents
  (Server Members, Message Content) must be enabled in the Developer Portal
  *and* the bot re-invited/restarted after.
- **`/shutdown_bot` says you're not authorized** — your user ID isn't in
  `OWNER_IDS` in `config.py`.
- **`pip install` fails on `databases`** — make sure you're on Python 3.10+
  and pip is up to date (`pip install --upgrade pip`).
