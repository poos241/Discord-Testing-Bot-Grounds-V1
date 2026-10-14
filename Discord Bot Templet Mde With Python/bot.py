# bot.py
import asyncio
import os
import random
from dotenv import load_dotenv
import discord
from discord.ext import commands

from config import statuses, GUILD_IDS

import datetime as DT

# Load token
load_dotenv()
TOKEN = os.getenv("TOKEN2")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True

client = commands.Bot(command_prefix="!", intents=intents)


# Load cogs
COGS = [
    "cogs.admin_cog",
    "cogs.fun_cog",
    "cogs.Level_system",
    "cogs.WatchList",
]

for cog in COGS:
    client.load_extension(cog)


@client.event
async def on_message(message):
    if message.guild is None and not message.author.bot:
        if message.content.lower() == "hi":
            await message.channel.send("Hello 👋 I work in DMs too!")
    await client.process_commands(message)  # let commands still run


async def change_status():
    while True:
        # Choose a random status
        status = random.choice(statuses)
        # Set the bot's status
        await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
        # Wait for a random amount of time (between 10 and 60 seconds)
        await asyncio.sleep(random.randint(10, 60))


@client.event
async def on_ready():
    # 🔍 Sanity check: syncing guild-specific commands fails with
    # 403 Missing Access if the bot isn't actually in every guild
    # listed in GUILD_IDS. Warn about it instead of cryptic tracebacks.
    missing = [gid for gid in GUILD_IDS if client.get_guild(gid) is None]
    if missing:
        print(f"⚠️ WARNING: the bot is not a member of these guilds from GUILD_IDS: {missing}")
        print("   Guild slash commands will fail to sync (403 Missing Access).")
        print("   Invite the bot to those servers, or remove the IDs from GUILD_IDS in config.py.")

    # ✅ Sync slash commands
    try:
        await client.sync_commands(force=True)
    except discord.Forbidden:
        print("❌ Command sync failed: 403 Missing Access.")
        print("   The bot is missing from a guild in GUILD_IDS, or a guild ID is wrong.")
        print("   Fix GUILD_IDS in config.py (or invite the bot), then restart.")
        return

    currentDT = DT.datetime.now()

    print(f"✅ Logged in as {client.user} (id: {client.user.id}) Commands synced! Time: {currentDT.strftime('%Y-%m-%d %H:%M:%S')}")

    # ✅ Start any background tasks
    client.loop.create_task(change_status())


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN2 is not set. Create a .env file next to bot.py with TOKEN2=your-bot-token")
    client.run(TOKEN)
