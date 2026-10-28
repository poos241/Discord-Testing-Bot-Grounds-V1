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
   ]
   ```
   The Logger package loads separately (`load_extension("cogs.Logger")`).

4. `on_ready` runs: it warns about guilds in `GUILD_IDS` the bot hasn't
   joined (slash sync would fail with 403 there), then calls
   `sync_commands(force=True)`.
5. A background task starts `change_status()`, which rotates the bot's
   presence every 10–60 seconds.
6. The web dashboard starts in a background thread: `create_app(bot)`
   builds the Flask app and `web/serve.py` serves it with waitress on
   `0.0.0.0:5000` (Flask dev server as fallback). Because the dashboard
   lives inside the bot process, restarting the bot restarts the
   dashboard too — and a restart is required after updating dashboard
   files, or new routes won't exist in the running app.

## Gotcha: views need a running loop

pycord `View` objects need a running event loop at creation, but cogs load
*before* the loop starts. That's why `fun_cog` defers creating its
persistent views until `on_ready` (`_ensure_view()`), and why the ticket
system registers its panel/close/claim/reopen views in `on_ready` too.

If you add buttons/views, do the same — **never build a `View` at import
time or in cog `__init__`**. (There used to be a regression test for
this, `test_noloop.py`, but no test files are currently in the repo —
the rule still stands.)
