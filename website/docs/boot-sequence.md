# Boot sequence

How `bot.py` starts the bot, step by step:

1. `load_dotenv()` reads `.env`; `TOKEN2` must be set or boot raises.
2. Intents: `members`, `voice_states`, `message_content`, and `presences`
   are enabled in code. Three of them are privileged and must also be
   enabled in the Developer Portal: Server Members, Message Content
   (the Logger needs it for message text), and Presence (online/offline
   status on the dashboard).
3. `commands.Bot` is created and every entry in `COGS` is loaded with
   `load_extension()`. **To add a cog, add its dotted path here:**

   ```python
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
       "cogs.Introduction",
       "cogs.Modlogs",
   ]
   ```
   The Logger package loads separately (`load_extension("cogs.Logger")`).
   Each `load_extension` is wrapped in its own try/except, so one broken
   cog logs loudly and the rest still load — a single bad cog file can
   never kill startup.

4. `on_ready` runs: it warns about guilds in `GUILD_IDS` the bot hasn't
   joined (slash sync would fail with 403 there), then calls
   `sync_commands(force=True)`.
5. A background task starts `change_status()`, which rotates the bot's
   presence every 10–60 seconds. A second `on_ready` (full reconnect)
   must not start a duplicate loop: the task handle is guarded
   (`_status_task`), and a finished task is restarted so the loop
   self-heals. Presence writes are skipped while the client is closed,
   and connection errors per tick are caught and logged — one dropped
   gateway write used to kill the task for good and freeze the status
   until restart.
6. The bridge API starts (`bridge_api.py`, guarded by `_bridge_task`
   the same way as the status loop): an aiohttp server on
   `127.0.0.1:5001` that the standalone website talks to. It only
   starts when `BRIDGE_SECRET` is set in `.env`; without it the bot
   logs `[ERROR] Bridge API will NOT start` and keeps running while
   the website degrades to 503s. A failed bridge start is never
   fatal to the bot.
7. The web dashboard does **not** start here anymore. Since November
   2026 it is a separate process: `python run_web.py` (or
   `run_web.bat`, which runs the watchdog around it). It serves on
   `127.0.0.1:5000` by default and talks to the bot only through the
   bridge. Starting the bot does not start the website, and stopping
   the bot does not stop it — each side has its own watchdog
   (`watchdog.py`: relaunch on exit 1 crash or exit 42 restart
   request; exit 0 stays stopped; more than 5 restarts in 60 seconds
   stops loudly). `WEB_ENABLED` is no longer read by the bot.

## Gotcha: views need a running loop

pycord `View` objects need a running event loop at creation, but cogs load
*before* the loop starts. That's why `fun_cog` defers creating its
persistent views until `on_ready` (`_ensure_view()`), and why the ticket
system registers its panel/close/claim/reopen views in `on_ready` too.

If you add buttons/views, do the same — **never build a `View` at import
time or in cog `__init__`**. (There used to be a regression test for
this, `test_noloop.py`, but no test files are currently in the repo —
the rule still stands.)
