import asyncio
from asyncio import tasks
import discord
import os
import json
import random
from discord.ext import commands
from discord.commands import Option

# Worker mode: Havenly Helper runs the SAME codebase with WORKER_MODE=1
# (set in its systemd unit, not in .env). In worker mode the bot logs
# in with WORKER_TOKEN, loads only WORKER_COGS (see bot.py), and its
# background loops / listeners are gated (see each cog). The main bot
# never sets WORKER_MODE, so this is False there and everything behaves
# exactly as today.
WORKER_MODE = os.getenv("WORKER_MODE", "").strip().lower() in (
    "1", "true", "yes", "on",
)


## guild ID's

GUILD_IDS = [1318042499784249415, 557680433245061130]

OWNER_IDS = [287282266261159937, 765094342279954509]

# Possible responses from the Magic Conch Shell
conch_responses = [
  "Yes.", "No.", "Maybe.", "Try again later.", "I don't think so.",
    "Absolutely!", "Never!", "It is certain.", "I doubt it."
]


# List of roast random statues
statuses = [
    "Havenly Bot 2.0 Here use /help for help"
    
]

# Presence lines for the worker (Havenly Helper). The main bot uses
# `statuses` above; the worker must not claim to be Havenly Bot 2.0.
worker_statuses = [
    "Havenly Helper — background jobs",
]


emojis = {
    "rock": "🪨",
    "paper": "📄",
    "scissors": "✂️"
}


COMMAND_TAGS = {
    "moderation": ["kick", "ban", "warn"],
    "levels": ["level", "leaderboard", "set_xp_rate", "set_cooldown", "set_level_channel", "add_xp", "resetxp", "cleardata", "getxpsettings"],
    "voicexp": ["voicexp optin", "voicexp optout", "voicexp status", "voicexp leaderboard", "voicexp config", "voicexp setrate", "voicexp setcap", "voicexp enable", "voicexp disable"],
    "backups": ["backup now", "backup status"],
    "tickets": ["ticket panel", "ticket config", "ticket show", "ticket open", "ticket close", "ticket reopen", "ticket claim", "ticket delete", "ticket add", "ticket remove", "ticket list"],
    "fun": ["eatyeet", "eatyeet_end", "eatyeet_leaderboard", "eatyeet_stats", "eatyeet_suggest", "eatyeet_history", "flip_coin", "conch", "roll", "rps", "leaderboard_rps", "clear_leaderboard_rps"],
    "utility": ["userinfo", "clear_user", "rename_user", "autocategorize", "diagnose_docs", "show_categories", "time"],
    "auto_thread": ["auto_thread", "set_auto_thread_channel", "remove_auto_thread_channel", "auto_thread_status"],
    "welcome": ["set_welcome_channel", "welcome_message", "welcome_embed_image", "welcome_embed_title", "welcome_embed_description"],
    "qotd": ["qotd today", "qotd history", "qotd submit", "qotd post", "qotd skip", "qotd config", "qotd pending", "qotd approve", "qotd reject", "qotd remove"],
    "appeals": ["appeal submit", "appeal list", "appeal review", "appeal config"],
    "lockdown": ["lockdown lock", "lockdown unlock", "lockdown lockall", "lockdown unlockall", "lockdown slowmode", "lockdown status"],
    "automod": ["automod status", "automod toggle", "automod config"],
    "badges": ["badge create", "badge award", "badge remove", "badge delete", "badge list"],
    "modnotes": ["modnotes search"],
    "custom_dm": ["set_reply_embed", "set_reply_image", "set_reply_title", "set_reply_description"],
    
    
    # Add more tags as needed...
}


COMMAND_HELP = {
    "kick": {
        "description": "Kicks a member",
        "usage": "/kick <member> [reason]",
        "example": "/kick @user Spamming in chat"
    },
    "ban": {
        "description": "Bans a member",
        "usage": "/ban <member> [reason]",
        "example": "/ban @user Breaking rules"
    },
    # add extras for each command...
}




answers = [
    "It is certain.",
    "It is decidedly so.",
    "You may rely on it.",
    "Without a doubt.",
    "Yes - definitely.",
    "As I see, yes.",
    "Most likely.",
    "Outlook good.",
    "Yes.",
    "Signs point to yes.",
    "Reply hazy, try again.",
    "Ask again later.",
    "Better not tell you now.",
    "Cannot predict now.",
    "Concentrate and ask again later.",
    "Don't count on it.",
    "My reply is no.",
    "My sources say no.",
    "Outlook not so good.",
    "Very doubtful.",
]



EVENT_TEMPLATES = {
    "Lewd": "Come hang out, play pool or vibe in the hot tub. Whatever way you want to chill, it's up to you as it's always a great way to meet new friends or get to know your friends better...",

    "Karaoke": "Warm up those vocal cords and come sing your heart out with everyone! Whether you're amazing or terrible, we want to hear it.",

    "Game Night": "Grab your favorite games and come enjoy a fun night hanging out, laughing, and gaming together.",

    "Movie Night": "Sit back, relax, and enjoy a cozy movie night with friends.",

    "Club": "Get ready to dance, vibe, and enjoy the music with everyone tonight.",

    "Drinking": "Grab your drinks and come chill responsibly with everyone for a fun social night.",

    "Chill": "Relax, socialize, meet new people, and enjoy a calm evening together.",

    "Custom": ""
}




# Dictionary to keep track of ongoing games
ongoing_games = {}
# Dictionary to track player stats
player_stats = {}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(DATA_DIR, exist_ok=True)

# JSON stores that now live in SQLite (bot.db) instead of data/*.json.
# The redirect is here, in the one load/save pair every cog and web
# blueprint already uses, so no call site had to change and the dict
# API is identical. The original JSON files are kept on disk untouched
# as the rollback copy; see utils/json_sqlite_store.py for the
# one-time migration, the per-store tables, and the rollback rules.
_SQLITE_JSON_FILES = frozenset({
    "mod_data.json",
    "watchlist_data.json",
    "eatyeet_stats.json",
    "eatyeet_suggestions.json",
    "eatyeet_active.json",
    "eatyeet_rematch.json",
})


def _atomic_write_json(path, data):
    """Write JSON to ``path`` atomically: temp file + ``os.replace``.

    A crash mid-write used to leave a torn half-written file, and the
    next load then silently reset it to ``{}`` (P3-35). Writing to a
    temp file in the same directory and renaming over the target makes
    the switch atomic — readers see either the old file or the new one,
    never a mix — and a failed write leaves the old file untouched.
    The temp file is removed on failure so no orphan ``.tmp`` is left.
    """
    tmp_path = path + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        raise
    # fsync the directory so the rename itself survives a crash.
    # POSIX only: Windows has no portable directory fsync, and the
    # atomic rename above still holds there.
    if os.name == "posix":
        try:
            dir_fd = os.open(os.path.dirname(path) or ".", os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            print(f"[WARN] Could not fsync directory for '{path}' (save still completed).")


def load_json(filename):
    if filename in _SQLITE_JSON_FILES:
        from utils.json_sqlite_store import load_store
        return load_store(filename)

    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        _atomic_write_json(path, {})
        return {}

    try:
        with open(path, 'r') as f:
            data = f.read().strip()
            if not data:
                return {}
            return json.loads(data)
    except json.JSONDecodeError:
        # File exists but is corrupted (e.g. torn by a pre-fix crash
        # mid-write). Preserve the bytes before resetting so the data
        # isn't silently lost — the .bak is the recovery copy.
        bak_path = path + ".bak"
        try:
            with open(bak_path, "w", encoding="utf-8") as bak:
                bak.write(data)
        except OSError:
            print(f"[WARN] '{filename}' is invalid JSON and the .bak copy could not be written. Resetting to empty dict.")
            return {}
        print(f"[WARN] '{filename}' is invalid JSON. Kept a copy at '{bak_path}' and reset to empty dict.")
        return {}
    except IOError:
        # File exists but could not be read (permissions, transient
        # error) — nothing to preserve, just report and reset.
        print(f"[WARN] Could not read '{filename}'. Returning empty dict.")
        return {}


def save_json(filename, data):
    if filename in _SQLITE_JSON_FILES:
        from utils.json_sqlite_store import save_store
        save_store(filename, data)
        return

    path = os.path.join(DATA_DIR, filename)
    _atomic_write_json(path, data)

def admin_required():
    async def predicate(ctx):
        if ctx.author.guild_permissions.administrator:
            return True
        else:
            await ctx.respond("⚠️ You need to be an administrator to use this command.", ephemeral=True)
            return False
    return commands.check(predicate)


def Manage_messages_required():
    async def predicate(ctx):
        if ctx.author.guild_permissions.manage_messages:
            return True
        else:
            await ctx.respond("⚠️ You need to have the 'Manage Messages' permission to use this command.", ephemeral=True)
            return False
    return commands.check(predicate)



def Manage_channels_required():
    async def predicate(ctx):
        if ctx.author.guild_permissions.manage_channels:
            return True
        else:
            await ctx.respond("⚠️ You need to have the 'Manage Channels' permission to use this command.", ephemeral=True)
            return False
    return commands.check(predicate)



def is_owner():
    async def predicate(ctx):
        if ctx.author.id in OWNER_IDS:
            return True
        await ctx.respond("⚠️ You are not authorized to use this command.", ephemeral=True)
        return False
    return commands.check(predicate)


def replace_placeholders(text, member):
        return text.replace("{mention}", member.mention).replace("{server}", member.guild.name)



# Helper function to update player stats
def update_stats(winner_id, loser_id):
    if winner_id not in player_stats:
        player_stats[winner_id] = {"wins": 0, "losses": 0}
    if loser_id not in player_stats:
        player_stats[loser_id] = {"wins": 0, "losses": 0}

    player_stats[winner_id]["wins"] += 1
    player_stats[loser_id]["losses"] += 1
##save_leaderboard()











def autocomplete_commands(
    self,
    ctx: discord.AutocompleteContext
    ):
    user_input = ctx.value.lower()

    suggestions = []
    for cmd in ctx.bot.application_commands:
        if user_input in cmd.name.lower():
            suggestions.append(cmd.name)

    return suggestions[:25]




def extra_help(text: str):
    def wrapper(func):
        setattr(func, "__extra_help__", text)
        return func
    return wrapper



