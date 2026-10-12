# Boot sequence

How `bot.py` starts the bot, step by step:

1. `load_dotenv()` reads `.env`; `TOKEN2` must be set or boot raises.
2. Intents: `members` and `voice_states` are privileged — they must also be
   enabled in the Developer Portal.
3. `commands.Bot` is created and every entry in `COGS` is loaded with
   `load_extension()`. **To add a cog, add its dotted path here:**

   ```python
   COGS = [
       "cogs.admin_cog",
       "cogs.fun_cog",
       "cogs.Level_system",
   ]
   ```

4. `on_ready` runs: it warns about guilds in `GUILD_IDS` the bot hasn't
   joined (slash sync would fail with 403 there), then calls
   `sync_commands(force=True)`.
5. A background task starts `change_status()`, which rotates the bot's
   presence every 10–60 seconds.

## Gotcha: views need a running loop

pycord `View` objects need a running event loop at creation, but cogs load
*before* the loop starts. That's why `fun_cog` defers creating its
persistent views until `on_ready` (`_ensure_view()`).

If you add buttons/views, do the same — **never build a `View` at import
time or in cog `__init__`**. There's a regression test for this
(`test_noloop.py`); run it if you touch view code.
