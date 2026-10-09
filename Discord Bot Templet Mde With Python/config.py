import asyncio
from asyncio import tasks
import discord
import os
import json
import random
import discord
from discord.ext import commands
from discord.commands import Option


## guild id 731453757388357642 for the house of fluff

GUILD_IDS = [1141240337076076554,731453757388357642]

OWNER_IDS = [287282266261159937, 765094342279954509]

# Possible responses from the Magic Conch Shell
conch_responses = [
  "Yes.", "No.", "Maybe.", "Try again later.", "I don't think so.",
    "Absolutely!", "Never!", "It is certain.", "I doubt it."
]


# List of roast random statues
statuses = [
    "Hello Nice To Meet You", "I'm in your walls ",
    "Say Hello to my little friend", "with myself", "VRChat","With a Kush bush", "you get high","myself get high", "you get high", "YouTube", "you play DDO", "you in your walls", "dice roll"
]


emojis = {
    "rock": "🪨",
    "paper": "📄",
    "scissors": "✂️"
}


COMMAND_TAGS = {
    "moderation": ["kick", "ban", "warn"],
    "levels": ["level", "leaderboard", "set_xp_rate", "set_cooldown", "set_level_channel", "add_xp", "resetxp", "cleardata", "getxpsettings", "backupdb"],
    "tickets": ["ticket_open", "ticket_close", "ticket_config", "ticket_manage_roles", "send_ticket_panel", "set_verification_role", "ticket_verification"],
    "fun": ["flip_coin", "conch", "roll", "rps", "leaderboard_rps", "clear_leaderboard_rps"],
    "utility": ["userinfo", "clear_user", "rename_user", "autocategorize", "diagnose_docs", "show_categories"],
    "auto_thread": ["auto_thread", "set_auto_thread_channel", "remove_auto_thread_channel", "auto_thread_status"],
    "welcome": ["set_welcome_channel", "welcome_message", "welcome_embed_image", "welcome_embed_title", "welcome_embed_description"],
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

def load_json(filename):
    path = os.path.join(DATA_DIR, filename)
    if not os.path.exists(path):
        with open(path, 'w') as f:
            json.dump({}, f)
        return {}

    try:
        with open(path, 'r') as f:
            data = f.read().strip()
            if not data:
                return {}
            return json.loads(data)
    except (json.JSONDecodeError, IOError):
        # File exists but is corrupted or unreadable
        print(f"⚠️ Warning: '{filename}' is invalid JSON. Resetting to empty dict.")
        return {}

def save_json(filename, data):
    path = os.path.join(DATA_DIR, filename)
    with open(path, "w", encoding='utf-8') as f:
        json.dump(data, f, indent=4)

    

def admin_required():
    async def predicate(self):
        if self.author.guild_permissions.administrator:
            return True
        else:
            await self.respond("⚠️ You need to be an administrator to use this command.", ephemeral=True)
            return False
    return commands.check(predicate)


def Manage_messages_required():
    async def predicate(self):
        if self.author.guild_permissions.manage_messages:
            return True
        else:
            await self.respond("⚠️ You need to have the 'Manage Messages' permission to use this command.", ephemeral=True)
            return False
    return commands.check(predicate)



def Manage_channels_required():
    async def predicate(self):
        if self.author.guild_permissions.manage_channels:
            return True
        else:
            await self.respond("⚠️ You need to have the 'Manage Channels' permission to use this command.", ephemeral=True)
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


