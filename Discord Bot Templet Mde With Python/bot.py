# bot.py
import asyncio
import os
import random
from dotenv import load_dotenv
import discord
from discord.ext import commands

from config import statuses

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
    # ✅ Sync slash commands
    await client.sync_commands(force=True)
    currentDT = DT.datetime.now()

    print(f"✅ Logged in as {client.user} (id: {client.user.id}) Commands synced! Time: {currentDT.strftime('%Y-%m-%d %H:%M:%S')}")

    # ✅ Start any background tasks
    client.loop.create_task(change_status())


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN2 is not set. Create a .env file next to bot.py with TOKEN2=your-bot-token")
    client.run(TOKEN)
