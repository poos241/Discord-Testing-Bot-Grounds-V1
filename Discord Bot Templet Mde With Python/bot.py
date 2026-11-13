import asyncio
import os
import random
import traceback
from dotenv import load_dotenv
import discord
from discord.ext import commands

from config import statuses, worker_statuses, GUILD_IDS, WORKER_MODE

import datetime as DT

# Load token
load_dotenv()
if WORKER_MODE:
    # Havenly Helper: its own token, never the main bot's.
    TOKEN = os.getenv("WORKER_TOKEN")
else:
    TOKEN = os.getenv("TOKEN2")

# Intents
intents = discord.Intents.default()
intents.members = True
intents.voice_states = True
intents.message_content = True  # required by the Logger cog to log message content
intents.presences = True  # required for online/offline status on the web dashboard

# auto_sync_commands=False in worker mode: pycord's on_connect
# auto-sync calls sync_commands() with no args, which iterates the
# commands' guild_ids (GUILD_IDS = LH + test). The worker is only in
# the test guild, so the LH lookup 403s and logs a traceback on every
# (re)connect. The explicit sync in on_ready (which passes the guilds
# the worker is actually in) is the only sync the worker needs. The
# main bot keeps the default (True) -- its on_ready sync is unchanged.
client = commands.Bot(
    command_prefix="!", intents=intents, auto_sync_commands=not WORKER_MODE
)


# Load cogs
COGS = [
    "cogs.admin_cog",
    "cogs.fun_cog",
    "cogs.Level_system",
    ##"cogs.VoiceXP",
    "cogs.WatchList",
    "cogs.DebugCog",
    "cogs.QOTD",
    ##"cogs.Tickets",
    ##"cogs.Backup",  # worker-only since the 2026-11-12 command split (Option C)
    ##"cogs.Appeals",
    "cogs.Lockdown",
    ##"cogs.Automod",
    ##"cogs.AutoThreads",
    ##"cogs.TimeCmd",
    ##"cogs.CustomBadges",
    "cogs.GHLog",
    ##"cogs.Permissions",  # worker-only since the 2026-11-12 command split (Option C)
    "cogs.Introduction",
    "cogs.Modlogs",
    "cogs.KumaHeartbeat",
    ##"cogs.ServerSettings",  # worker-only since the 2026-11-12 command split (Option C)
    "cogs.Help_Info_Doc",
]

# Worker cogs (Havenly Helper): background / data work + setup commands.
# The worker loads ONLY these; the main bot loads the full COGS list
# (plus cogs.Logger, loaded below in both modes -- see its comment).
# The 7 commented-out cogs stay commented out in both modes.
# Per-cog reasons (see README for the full table):
#   Introduction -- /intro scan job + intro commands; its 4 real-time
#       listeners are gated to the main bot (see cogs/Introduction.py).
#   Modlogs -- /modlogs scan job + modlog commands; no loops/listeners.
#   GHLog -- /banlog collect/backfill jobs + ban-log commands.
#   Backup -- daily snapshot loop (worker-only) + /backup commands.
#   admin_cog -- timeout-board refresh + tempban sweep loops
#       (worker-only) + mod commands. Its on_member_update listener is
#       gated to the main bot so manual timeouts are recorded once.
#   KumaHeartbeat -- worker heartbeat (WORKER_KUMA_PUSH_URL; off if
#       unset, so it never pushes to the main bot's Kuma monitor).
#   Logger -- ONLY its /logs + /log_toggle commands (setup, worker-only).
#       Its 8 event-listener cogs are gated to the main bot in
#       cogs/Logger/__init__.py, so the worker never double-logs.
#   WatchList -- ONLY /watch set_channel (setup, worker-only). Its
#       on_message listener is gated to the main bot in cogs/WatchList.py.
#   QOTD -- ONLY /qotd config (setup, worker-only). Its daily posting
#       loop is gated to the main bot in cogs/QOTD.py.
#   Permissions -- /perm commands (setup, worker-only). The custom
#       permission system reads the shared command_permissions table,
#       so grants written by the Helper are enforced by both bots.
#   ServerSettings -- /bot_settings (view, worker-only). Command-only.
# NOT loaded by the worker: cogs.Level_system (levels -- the worker
# must not write level data; its only level writes are admin_cog's
# /userinfo panel buttons, which go through the shared Postgres
# advisory lock), cogs.Lockdown, and all user-facing / game cogs
# (fun, Help, DebugCog) plus the 7 disabled cogs.
WORKER_COGS = [
    "cogs.Introduction",
    "cogs.Modlogs",
    "cogs.GHLog",
    "cogs.Backup",
    "cogs.admin_cog",
    "cogs.KumaHeartbeat",
    "cogs.Logger",
    "cogs.WatchList",
    "cogs.QOTD",
    "cogs.Permissions",
    "cogs.ServerSettings",
]

for cog in (WORKER_COGS if WORKER_MODE else COGS):
    try:
        client.load_extension(cog)
    except Exception as e:
        print(f"[ERROR] Failed to load cog {cog}: {e!r}")
        traceback.print_exc()

# The Logger loads in BOTH modes since the 2026-11-12 command split
# (Option C): its /logs + /log_toggle setup commands live on the worker,
# while its 8 event-listener cogs stay on the main bot (gated in
# cogs/Logger/__init__.py, so the worker never double-logs). The
# event-history prune loop runs on the main bot (gated in
# cogs/Logger/commands.py). In worker mode the cog comes in through
# WORKER_COGS above, so only load it here in main mode (loading it
# twice raises ExtensionAlreadyLoaded).
if not WORKER_MODE:
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
        # Worker mode: the bridge is the job hub (port 5002, set in the
        # worker's systemd unit via BRIDGE_PORT), not the website API.
        await start_bridge(client, worker=WORKER_MODE)
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
                # Choose a random status (the worker has its own lines
                # so it never claims to be Havenly Bot 2.0).
                pool = worker_statuses if WORKER_MODE else statuses
                status = random.choice(pool)
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
    # [OK] Postgres (2026-11-12): connect the database ONCE, here,
    # before anything else in on_ready touches it. The per-cog
    # connect() calls in the before_loop hooks are serialised to
    # no-ops by SerialisedDatabase in data/DB/db.py, so this is the
    # single intentional connect. A failure only logs (the loops'
    # own connect() calls retry on their own before_loop).
    try:
        from data.DB.db import database
        await database.connect()
    except Exception as e:
        print(f"[ERROR] Database connect failed in on_ready: {e!r}")

    # Worker mode: the worker is only in the guilds it was invited to
    # (the test guild for now). Sync its commands to exactly those
    # guilds: syncing to a guild the bot is not in raises 403 and
    # aborts the whole sync (pycord registers guild commands one guild
    # at a time), so the static GUILD_IDS list is wrong for the worker.
    # The main bot syncs to GUILD_IDS as today (it is in both guilds).
    sync_guild_ids = None
    if WORKER_MODE:
        sync_guild_ids = [g.id for g in client.guilds]
        if not sync_guild_ids:
            print("[WARN] WARNING: the worker is not in any guild; no commands will sync.")
            print("   Invite Havenly Helper to a server, then restart it.")
        else:
            print(f"[INFO] Worker mode: syncing commands to guilds {sync_guild_ids}")
    else:
        # Sanity check: syncing guild-specific commands fails with
        # 403 Missing Access if the bot isn't actually in every guild
        # listed in GUILD_IDS. Warn about it instead of cryptic tracebacks.
        missing = [gid for gid in GUILD_IDS if client.get_guild(gid) is None]
        if missing:
            print(f"[WARN] WARNING: the bot is not a member of these guilds from GUILD_IDS: {missing}")
            print("   Guild slash commands will fail to sync (403 Missing Access).")
            print("   Invite the bot to those servers, or remove the IDs from GUILD_IDS in config.py.")

    # [OK] Command merge (2026-11-11): rename stored permission grants
    # for the merged families BEFORE the sync, so the new subcommand
    # keys find the grants the admins set up under the old names.
    # Idempotent; a failure only logs and never blocks startup.
    try:
        from data.DB.Storage.storage import migrate_renamed_command_permissions
        await migrate_renamed_command_permissions()
    except Exception as e:
        print(f"[WARN] grant-rename migration failed: {e!r}")

    # [OK] Sync slash commands. A sync failure must not kill the rest of
    # startup: the bot, the status rotation, and the bridge API all
    # still start (this is what the 2026-10-29 GHLog 400 broke).
    synced = True
    try:
        await client.sync_commands(force=True, guild_ids=sync_guild_ids)
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
        if WORKER_MODE:
            raise RuntimeError(
                "WORKER_TOKEN is not set. Add WORKER_TOKEN=<helper bot token> "
                "to the .env file next to bot.py"
            )
        raise RuntimeError("TOKEN2 is not set. Create a .env file next to bot.py with TOKEN2=your-bot-token")
    client.run(TOKEN)
