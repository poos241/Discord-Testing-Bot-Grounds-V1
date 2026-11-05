import asyncio
import os
import random
import traceback
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
intents.message_content = True  # required by the Logger cog to log message content
intents.presences = True  # required for online/offline status on the web dashboard

client = commands.Bot(command_prefix="!", intents=intents)


# Load cogs
COGS = [
    "cogs.admin_cog",
    "cogs.fun_cog",
    "cogs.Level_system",
    "cogs.VoiceXP",
    "cogs.WatchList",
    "cogs.DebugCog",
    "cogs.QOTD",
    "cogs.Tickets",
    "cogs.Backup",
    "cogs.Appeals",
    "cogs.Lockdown",
    "cogs.Automod",
    "cogs.AutoThreads",
    "cogs.TimeCmd",
    "cogs.CustomBadges",
    "cogs.GHLog",
    "cogs.Permissions",
    "cogs.Introduction",
    "cogs.Modlogs",
    "cogs.KumaHeartbeat",
    "cogs.ServerSettings",
]

for cog in COGS:
    try:
        client.load_extension(cog)
    except Exception as e:
        print(f"[ERROR] Failed to load cog {cog}: {e!r}")
        traceback.print_exc()
try:
    client.load_extension("cogs.Logger")
except Exception as e:
    print(f"[ERROR] Failed to load cog cogs.Logger: {e!r}")
    traceback.print_exc()

@client.event
async def on_message(message):
    if message.guild is None and not message.author.bot:
        if message.content.lower() == "hi":
            await message.channel.send("Hello ð I work in DMs too!")
    await client.process_commands(message)  # let commands still run


# Set when the status-rotation task is started, so a second on_ready
# (full reconnect) does not start a duplicate loop.
_status_task = None

# Set when the bridge API task is started. Same reconnect rule as the
# status loop: start once from on_ready, restart if it ever finished.
_bridge_task = None


async def _run_bridge():
    """Start the bridge API the standalone website talks to.

    A failed bridge start is logged, never fatal: the bot keeps
    running and the website degrades to 503s until the bridge is up.
    """
    try:
        from bridge_api import start_bridge
        await start_bridge(client)
    except Exception:
        print("[ERROR] Bridge API failed unexpectedly; the website will degrade to 503s.")
        traceback.print_exc()


async def change_status():
    # The presence write can fail when the gateway connection drops
    # (PC slept, network blip, Discord reset): the websocket is closing
    # and change_presence raises ClientConnectionResetError. That used to
    # kill this task for good, leaving the bot with a frozen status until
    # the next restart. Never let one bad tick kill the loop.
    while True:
        try:
            if not client.is_closed():
                # Choose a random status
                status = random.choice(statuses)
                # Set the bot's status
                await client.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
        except (discord.DiscordException, OSError) as e:
            print(f"[WARN] Status rotation skipped (connection issue): {e!r}")
        except Exception:
            print("[ERROR] Status rotation failed unexpectedly; will retry next tick.")
            traceback.print_exc()
        # Wait for a random amount of time (between 10 and 60 seconds)
        await asyncio.sleep(random.randint(10, 60))


@client.event
async def on_ready():
    # ð Sanity check: syncing guild-specific commands fails with
    # 403 Missing Access if the bot isn't actually in every guild
    # listed in GUILD_IDS. Warn about it instead of cryptic tracebacks.
    missing = [gid for gid in GUILD_IDS if client.get_guild(gid) is None]
    if missing:
        print(f"[WARN] WARNING: the bot is not a member of these guilds from GUILD_IDS: {missing}")
        print("   Guild slash commands will fail to sync (403 Missing Access).")
        print("   Invite the bot to those servers, or remove the IDs from GUILD_IDS in config.py.")

    # [OK] Sync slash commands. A sync failure must not kill the rest of
    # startup: the bot, the status rotation, and the bridge API all
    # still start (this is what the 2026-10-29 GHLog 400 broke).
    synced = True
    try:
        await client.sync_commands(force=True)
    except discord.Forbidden:
        synced = False
        print("[ERROR] Command sync failed: 403 Missing Access.")
        print("   The bot is missing from a guild in GUILD_IDS, or a guild ID is wrong.")
        print("   Fix GUILD_IDS in config.py (or invite the bot), then restart.")
    except Exception as e:
        synced = False
        print(f"[ERROR] Command sync failed: {e!r}")
        print("   Slash commands may be out of date; the bot, status rotation,")
        print("   and bridge API will still start. Fix the cause and restart to re-sync.")

    currentDT = DT.datetime.now()

    who = f"{client.user} (id: {client.user.id})" if client.user else "unknown user"
    if synced:
        print(f"[OK] Logged in as {who} Commands synced! Time: {currentDT.strftime('%Y-%m-%d %H:%M:%S')}")
    else:
        print(f"[WARN] Logged in as {who} Commands NOT synced (see error above). Time: {currentDT.strftime('%Y-%m-%d %H:%M:%S')}")

    # [OK] Start any background tasks (once: a full reconnect re-runs
    # on_ready, and must not start a second status loop; a finished task
    # is restarted so the loop self-heals).
    global _status_task, _bridge_task
    if _status_task is None or _status_task.done():
        _status_task = client.loop.create_task(change_status())

    # [OK] Start the bridge API the standalone website talks to --
    # once only, for the same reconnect reason as the status loop.
    # (The in-process website is gone: the website now runs as its own
    # process; WEB_ENABLED is no longer read by the bot.)
    if _bridge_task is None or _bridge_task.done():
        _bridge_task = client.loop.create_task(_run_bridge())
    print("[INFO] The website now runs as a separate process; the bot no longer starts it in-process.")


if __name__ == "__main__":
    if not TOKEN:
        raise RuntimeError("TOKEN2 is not set. Create a .env file next to bot.py with TOKEN2=your-bot-token")
    client.run(TOKEN)
