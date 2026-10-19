{"ok":true,"result":{"content":[{"text":"successfully downloaded text file (SHA: ace3b12958d0e989fb45d95377b4c729621b76f0)","type":"text"},{"resource":{"mimeType":"text/plain; charset=utf-8","text":"# bot.py
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
TOKEN = os.getenv(\"TOKEN2\")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True  # required by the Logger cog to log message content
intents.presences = True  # required for online/offline status on the web dashboard

client = commands.Bot(command_prefix=\"!\", intents=intents)


# Load cogs
COGS = [
    \"cogs.admin_cog\",
    \"cogs.fun_cog\",
    \"cogs.Level_system\",
    \"cogs.WatchList\",
]

for cog in COGS:
    client.load_extension(cog)
client.load_extension(\"cogs.Logger\")

@client.event
async def on_message(message):
    if message.guild is None and not message.author.bot:
        if message.content.lower() == \"hi\":
            await message.channel.send(\"Hello 👋 I work in DMs too!\")
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
        print(f\"⚠️ WARNING: the bot is not a member of these guilds from GUILD_IDS: {missing}\")
        print(\"   Guild slash commands will fail to sync (403 Missing Access).\")
        print(\"   Invite the bot to those servers, or remove the IDs from GUILD_IDS in config.py.\")

    # ✅ Sync slash commands
    try:
        await client.sync_commands(force=True)
    except discord.Forbidden:
        print(\"❌ Command sync failed: 403 Missing Access.\")
        print(\"   The bot is missing from a guild in GUILD_IDS, or a guild ID is wrong.\")
        print(\"   Fix GUILD_IDS in config.py (or invite the bot), then restart.\")
        return

    currentDT = DT.datetime.now()

    print(f\"✅ Logged in as {client.user} (id: {client.user.id}) Commands synced! Time: {currentDT.strftime('%Y-%m-%d %H:%M:%S')}\")

    # ✅ Start any background tasks
    client.loop.create_task(change_status())

    # ✅ Start the web dashboard (Flask in a background thread)
    if os.getenv(\"WEB_ENABLED\", \"true\").lower() in (\"1\", \"true\", \"yes\"):
        try:
            import threading
            from web.app import create_app
            web_app = create_app(client)
            web_host = os.getenv(\"WEB_HOST\", \"0.0.0.0\")
            web_port = int(os.getenv(\"WEB_PORT\", \"5000\"))
            threading.Thread(
                target=web_app.run,
                kwargs={\"host\": web_host, \"port\": web_port,
                        \"debug\": False, \"use_reloader\": False},
                daemon=True, name=\"web-ui\",
            ).start()
            print(f\"🌐 Web dashboard running at http://{web_host}:{web_port}\")
        except Exception as e:
            print(f\"⚠️ Web dashboard failed to start: {e!r}\")


if __name__ == \"__main__\":
    if not TOKEN:
        raise RuntimeError(\"TOKEN2 is not set. Create a .env file next to bot.py with TOKEN2=your-bot-token\")
    client.run(TOKEN)
","uri":"repo://poos241/Discord-Testing-Bot-Grounds-V1/sha/f1760da1dcb3da6dbe942e3d371f10a197cea6f6/contents/Discord%20Bot%20Templet%20Mde%20With%20Python/bot.py"},"type":"resource"}]},"tool_name":"get_file_contents"}
