# Boot sequence

How `bot.py` starts the bot, step by step. The same file boots **both**
bots — the `WORKER_MODE` environment variable picks which one
(`WORKER_MODE=1` = Havenly Helper, unset = Havenly Bot 2.0). The
Helper's systemd unit sets `WORKER_MODE=1`; the variable is **not** in
`.env` (the main bot reads the same `.env`, so it must not be there).

1. `load_dotenv()` reads `.env`; the token must be set or boot raises —
   `TOKEN2` for the main bot, `WORKER_TOKEN` for the Helper.
2. Intents: `members`, `voice_states`, `message_content`, and `presences`
   are enabled in code. Three of them are privileged and must also be
   enabled in the Developer Portal: Server Members, Message Content
   (the Logger needs it for message text), and Presence (online/offline
   status on the dashboard). The Helper needs all three too.
3. `commands.Bot` is created and every entry in the cog list is loaded
   with `load_extension()`. **To add a cog, add its dotted path to the
   right list** — `COGS` for the main bot, `WORKER_COGS` for the Helper
   (see below). Each `load_extension` is wrapped in its own
   try/except, so one broken cog logs loudly and the rest still load
   — a single bad cog file can never kill startup.

   ```python
   # Main bot (WORKER_MODE unset) — 12 entries + Logger below
   COGS = [
       "cogs.admin_cog",
       "cogs.fun_cog",
       "cogs.Level_system",
       "cogs.WatchList",
       "cogs.DebugCog",
       "cogs.QOTD",
       "cogs.Lockdown",
       "cogs.GHLog",
       "cogs.Introduction",
       "cogs.Modlogs",
       "cogs.Help_Info_Doc",
       "cogs.KumaHeartbeat",
   ]

   # Helper (WORKER_MODE=1) — 11 entries
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
   ```

   The Logger package loads separately (`load_extension("cogs.Logger")`,
   main mode only — in worker mode it comes in through `WORKER_COGS`).
   Some cogs load in **both** modes and gate their own behaviour:
   Logger's 8 listener cogs are main-only (loading them on the Helper
   would log every event twice) while its `/logs` + `/log_toggle`
   commands go to the Helper; Introduction's listeners are main-only
   while its setup/scan commands are Helper-only; QOTD posting is
   main-only while `/qotd config` is Helper-only; `admin_cog`'s
   board-refresh + tempban-sweep loops run only on the Helper.
   `Backup`, `Permissions`, and `ServerSettings` were removed from
   main `COGS` in the 2026-11-13 command split — they are Helper-only
   now.

   > **Deliberately disabled cogs.** Seven cogs are commented out in
   > `bot.py` and their commands are **not registered** on either bot:
   > VoiceXP, Tickets, Appeals, Automod, AutoThreads, TimeCmd, and
   > CustomBadges (disabled 2026-11-12, intentional). Do not uncomment
   > them. That is why the live counts are main 54 top-level / 83
   > runnable and Helper 11 / 30 — not the pre-disable totals.

4. `on_ready` runs: first a single explicit `await database.connect()`
   at the top — the database connection is serialised through one
   `asyncio.Lock` in `SerialisedDatabase` (`data/DB/db.py`), because
   concurrent `connect()` calls race inside the `databases` library
   (0.9.0) and can leave the connection stuck acquired so every later
   database operation fails. The `on_ready` connect happens before
   the guild sanity check, the grant-rename migration, and the sync;
   per-cog `connect()` calls after that are safe no-ops. Then it warns
   about guilds in `GUILD_IDS` the bot hasn't joined (slash sync would
   fail with 403 there), then calls
   `sync_commands(force=True, guild_ids=sync_guild_ids)`.

   **Sync rules.** The main bot syncs to `GUILD_IDS` (test server +
   Little Haven). The Helper syncs to `client.guilds` — the guilds it
   is actually in — because syncing to a guild it hasn't joined 403s
   and aborts the whole sync. The Helper only syncs **at startup**:
   invite it to a new guild and its commands will not appear there
   until you restart `havenly-helper`. The Helper also runs with
   `auto_sync_commands=False` — pycord's on-connect auto-sync would
   otherwise try the LH lookup and 403 on connect. The main bot keeps
   auto-sync on (default).
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
   `127.0.0.1:5001` for the main bot (full API) or `127.0.0.1:5002`
   for the Helper (worker hub: status + jobs only — `backup_now`,
   `board_refresh`, `main_status`). It only starts when
   `BRIDGE_SECRET` is set in `.env`; without it the bot logs
   `[ERROR] Bridge API will NOT start` and keeps running while the
   website degrades to 503s. A failed bridge start is never fatal to
   the bot.
7. The web dashboard does **not** start here anymore. Since November
   2026 it is a separate process: `python run_web.py` (or
   `run_web.bat`, which runs the watchdog around it). It serves on
   `127.0.0.1:5000` by default and talks to the bots only through the
   bridges. Starting a bot does not start the website, and stopping a
   bot does not stop it — each side has its own watchdog
   (`watchdog.py`: relaunch on exit 1 crash or exit 42 restart
   request; exit 0 stays stopped; more than 5 restarts in 60 seconds
   stops loudly). `WEB_ENABLED` is no longer read by the bot.

## Gotcha: views need a running loop

pycord `View` objects need a running event loop at creation, but cogs load
*before* the loop starts. That's why `fun_cog` defers creating its
persistent views until `on_ready` (`_ensure_view()`).

> **Tickets is disabled**, so the old note about the ticket system
> registering its panel/close/claim/reopen views in `on_ready` is
> historical — but the rule it illustrates still stands for every
> persistent view.

If you add buttons/views, do the same — **never build a `View` at import
time or in cog `__init__`**. (There used to be a regression test for
this, `test_noloop.py`, but no test files are currently in the repo —
the rule still stands.)

## Useful commands

Commands for running the bots and the website. The full reference
with per-OS variants lives in the README ("Useful commands"); this
is the same list, handbook-side.

### Generating a bridge secret

Any of these produces a suitable secret (32 random bytes, base64).
Run it on the machine that will run the bot, then put the output in
`.env` as `BRIDGE_SECRET=<output>` (one line, no quotes, no spaces).
Each machine needs its own secret.

Windows (PowerShell):

```powershell
$b = New-Object byte[] 32; [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b); [Convert]::ToBase64String($b)
```

Linux or macOS (terminal):

```bash
openssl rand -base64 32
```

Any system (Python is already installed for the bot):

```bash
python -c "import secrets; print(secrets.token_urlsafe(36))"
```

### Start, stop, restart

Three processes, three services on the home server:

| Process | Service | Manual start |
| --- | --- | --- |
| Main bot | `kushbot` | `python bot.py` |
| Helper | `havenly-helper` | `WORKER_MODE=1 python bot.py` |
| Website | `kushweb` | `python run_web.py` |

Windows: `run_bot.bat` / `run_web.bat`, or `python bot.py` /
`python run_web.py` from the bot folder (the Helper on Windows is
`set WORKER_MODE=1` then `python bot.py` in a third window).
Linux (systemd, home server): `sudo systemctl start|stop|restart|status
kushbot.service havenly-helper.service kushweb.service`. macOS / plain
Linux: `python3 bot.py` / `python3 run_web.py` in a terminal.

The server-home page has Restart bot and Restart website buttons
(admin-only); Discord has `/restart_bot` and `/restart_web` (bot
owner only, main bot). There is **no Discord command to restart the
Helper** — restart it with `systemctl` (deliberate: the same command
name doing different things on two bots would be confusing).
Restarting just one side:

```bash
sudo systemctl restart kushweb.service          # just the website
sudo systemctl restart kushbot.service          # just the main bot
sudo systemctl restart havenly-helper.service   # just the Helper
```

**Restart the Helper after inviting it to a new guild** — it only
syncs commands at startup, so its commands won't appear there until
it restarts.

### Check they're running

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:5000/
curl -H "X-Bridge-Secret: <your bridge secret>" http://127.0.0.1:5001/bridge/status
curl -H "X-Bridge-Secret: <your bridge secret>" http://127.0.0.1:5002/status
```

`200` from the first means the website is up; the bridge calls answer
JSON with `"ready": true` when healthy (a `401` means the secret is
wrong or missing). On the home server, `~/servers/kush-status.sh`
prints the services, their ports, and recent logs on one screen.

### Logs

Windows: each side logs to its own console window. Linux
(systemd): `journalctl -u kushbot.service -n 50 --no-pager`,
`journalctl -u havenly-helper.service -n 50 --no-pager`,
`journalctl -u kushweb.service -f`.

### Update the code

```bash
git pull                 # from the repo root
git log --oneline -3     # what version is running?
```

Restart the changed side after a pull (dashboard-only changes
need only the website restarted). A Helper change needs
`havenly-helper` restarted — and remember its commands only re-sync
at startup.

### Uptime Kuma

Kuma (Docker on the home server, UI at http://127.0.0.1:3001 on
that machine) watches the website with an HTTP check on
`http://<server-tailscale-ip>:5000/` (the website's address on the
home server's Tailscale network). Each bot is watched with its own Push
monitor instead — neither bot has an HTTP endpoint of its own, so
each pushes its own heartbeat (`cogs/KumaHeartbeat.py`): create a
Push monitor in Kuma with Heartbeat Interval 60s, put the push URL
Kuma gives you in `.env` — `KUMA_PUSH_URL=http://127.0.0.1:3001/api/push/<key>`
for the main bot, `WORKER_KUMA_PUSH_URL=http://127.0.0.1:3001/api/push/<key>`
for the Helper (a separate monitor per bot; the Helper never pushes
to the main bot's monitor) — then restart that bot. Each bot pushes
every 30s (`KUMA_PUSH_INTERVAL_SECONDS`, default 30); keep the push
interval at half Kuma's Heartbeat Interval or less. A push URL is a
key: never commit it, never share it. Without its push URL a bot's
heartbeat is off and it logs one `[KUMA] ... disabled` line at
startup.
