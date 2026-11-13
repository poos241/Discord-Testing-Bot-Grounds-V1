# Two bots

The bot system runs as **two Discord bots sharing one codebase and
one database**. This page is the overview; the command-by-command
split is in [Commands](./commands.md), and the database is in
[PostgreSQL](./postgres.md).

| Bot | Identity | Role | Commands |
| --- | --- | --- | --- |
| **Havenly Bot 2.0** (main bot) | id `1568749855105360023` | The face of the system. Real-time moderation, levels, games, QOTD, help — everything a mod or member does in the moment. | 54 top-level / 83 runnable |
| **Havenly Helper** (worker bot) | id `1570524098159976488` | The back office. Setup and config, batch jobs (scans, backfills, backups), and the timeout board. | 11 top-level / 30 runnable |

Counts are the live Discord registrations, verified 2026-11-13
against the Discord API on both guilds. The two bots register the
**same guilds** (the test server and Little Haven) and share
**zero commands** — every command lives on exactly one bot, so there
is never any doubt which bot to use.

## Same codebase, one flag

Both bots run the same code. The only difference is the
`WORKER_MODE` environment variable:

| Process | Command | Service (systemd) |
| --- | --- | --- |
| Main bot | `python bot.py` | `kushbot` |
| Helper (worker) | `WORKER_MODE=1 python bot.py` | `havenly-helper` |
| Website | `python run_web.py` | `kushweb` |

When `WORKER_MODE` is set, `bot.py` loads the worker cog set
(`WORKER_COGS`), uses the `WORKER_TOKEN`, registers only the
Helper's commands, and starts the worker bridge hub on port 5002.
When it is not set, it loads the full cog set, uses `TOKEN2`,
registers the main bot's commands, and starts the main bridge on
port 5001. The systemd unit for the Helper sets `WORKER_MODE=1`;
the variable is **not** in `.env` (it must not be — the main bot
reads the same `.env`).

The two bots never talk via Discord messages. They share the
Postgres database (see [PostgreSQL](./postgres.md)) and ask each
other to do work via the bridge hub, below.

## What the Helper loads

`WORKER_COGS` (11 entries): `cogs.admin_cog`, `cogs.Introduction`,
`cogs.Modlogs`, `cogs.GHLog`, `cogs.Backup`, `cogs.KumaHeartbeat`,
`cogs.Logger`, `cogs.WatchList`, `cogs.QOTD`, `cogs.Permissions`,
`cogs.ServerSettings`.

Some of those cogs are shared with the main bot and gated
per-command or per-listener (see [Commands](./commands.md)):

- **Logger** loads in both modes — its 8 listener cogs are gated
  to main-only (loading them on the worker would log every event
  twice), its `/logs` + `/log_toggle` commands go to the worker,
  and its prune loop is main-only.
- **Introduction** listeners (`on_message`, `on_member_join`,
  `on_raw_message_delete`, `on_member_update`) are main-only — if
  the worker ran them too, every intro post would be marked twice.
- **admin_cog**'s `on_member_update` listener is main-only so
  manual timeouts are recorded once; its timeout-board refresh +
  tempban sweep loops are worker-only.
- **QOTD**'s posting loop is main-only (the worker running it
  would double-post); the QOTD config command is worker-only.
- **WatchList**'s `on_message` listener is main-only.

**Not loaded by the worker:** `cogs.Level_system` (the worker must
not run level grants — all 24 level commands stay on the main bot),
`cogs.Lockdown` (auto-unlock stays on the main bot), the user-facing
and game cogs (`fun_cog`, `DebugCog`, `Help_Info_Doc`), and the 7
deliberately disabled cogs (VoiceXP, Tickets, Appeals, Automod,
AutoThreads, TimeCmd, CustomBadges — commented out in both modes).

The worker's only level write paths are the `/userinfo` panel
buttons (add XP, remove XP, wipe data) in `admin_cog`, and all of
them go through the shared Postgres advisory lock
(`get_level_lock()`), so they are cross-process safe against the
main bot's grants.

## The command split (Option C)

The split is **setup vs. use**: if a command does something *right
now* for a member or a mod, it lives on the main bot; if it *sets
something up* or *runs a batch job*, it lives on the Helper. All 24
level commands stay on the main bot.

**Helper-only:** `/timeout_board`, `/intro set_channel` / `set_role`
/ `toggle` / `scan` / `settings`, `/modlogs scan`, `/banlog
set_channel` / `collect` / `backfill_cases`, `/backup now` /
`status`, `/logs setup` / `change_channel` / `settings`,
`/log_toggle` (all 5 groups), `/watch set_channel`, `/qotd config`,
`/perm` (all 7), `/bot_settings`.

**Main keeps everything else**, including `/timeout`, `/clear_user`,
`/userinfo`, `/banlog log` / `approve` / `update` / `delete`,
`/intro check` + the Check Introduction context menu, `/modlogs
list` / `recap` / `edit` / `actions`, all level commands,
`/restart_bot`, `/restart_web`, `/shutdown_bot`, `/help`, `/debug`,
games, QOTD except config, lockdown, and watch except
`set_channel`.

The split is implemented by cog-level lists (`COGS` vs
`WORKER_COGS`) plus per-command `WORKER_MODE` gating at class
level in the shared cogs — see [Commands](./commands.md).

## The bridge hub

The two bots (and the website) talk over local HTTP bridges, all
on localhost only, all authenticated with the shared
`X-Bridge-Secret` header (a wrong secret gets a 401, an unknown job
gets a 404).

| | Main bot bridge | Helper bridge |
| --- | --- | --- |
| Address | `127.0.0.1:5001` | `127.0.0.1:5002` |
| What it does | Full API (moderation actions, profiles, levels, backups, …) | Status + jobs only |
| Jobs | — | `backup_now`, `board_refresh`, `main_status` |

- **Main bridge (5001):** the full route set the website talks to.
  The main bot is the sole Discord actor for moderation.
- **Worker hub (5002):** `GET /status` plus `POST /jobs/{job}`
  only. It rejects the website routes (404). Jobs:
  `backup_now` (take a manual snapshot, same code as
  `/backup now`), `board_refresh` (refresh one guild's timeout
  board now, given a `guild_id`), `main_status` (GETs the main
  bot's bridge `/status` — proves worker → main; a read, never an
  action).
- **Website reaches both bots.** `GET /api/bots` returns the status
  of the main bot and the Helper, so the dashboard's bot-status page
  shows both.

One direction is worth knowing about: when the main bot runs
`/timeout`, it fire-and-forget POSTs the worker hub's
`board_refresh` job so the board updates at once; the worker's
own 5-minute board-refresh sweep is the fallback if that call
fails. Bridge-triggered scans/backfills (`intro_scan`,
`modlog_scan`, `banlog_collect`, `ghlog_backfill_cases`) are not
wired up yet — those jobs run via the Helper's slash commands for
now.

## Sync-on-startup rule

Both bots sync their commands at startup (`on_ready`), and **only**
at startup. The Helper's sync goes to the guilds it is actually in
(`client.guilds`) — it must not sync to a guild it has not joined,
or the lookup 403s and aborts the whole sync. Consequences:

- **Inviting the Helper to a new guild needs a `havenly-helper`
  restart before its commands appear there.** The worker does not
  re-sync on guild join. (This bit the team on 2026-11-12/13: the
  Helper was invited to Little Haven and its commands did not show
  up until a restart.)
- The worker disables pycord's auto-sync
  (`auto_sync_commands=not WORKER_MODE`) because the auto-sync
  looks up `GUILD_IDS` and 403s on guilds the worker has not
  joined. Its explicit `on_ready` sync is the only sync.
- There is no Discord command to restart the Helper — restart it
  with `systemctl restart havenly-helper.service`. That is
  deliberate: the same command name doing different things on two
  bots would be confusing.

## Uptime Kuma coverage

Kuma watches all three processes, each a different way:

- **Website** — HTTP check (Kuma pulls the dashboard URL on the
  server's Tailscale address).
- **Main bot** — Push check. The bot pushes its own heartbeat every
  30s to the URL in `KUMA_PUSH_URL`; Kuma marks it DOWN if no push
  arrives within its 60s interval.
- **Helper** — Push check, same shape, separate monitor, URL in
  `WORKER_KUMA_PUSH_URL`. The worker heartbeat is disabled until
  that monitor exists (it logs one line at startup and never pushes
  to the main bot's monitor). Until then, check Helper health with
  `systemctl status havenly-helper` or the worker bridge `/status`
  endpoint.

See the README's [Uptime Kuma](https://github.com/poos241/Discord-Testing-Bot-Grounds-V1#uptime-kuma)
section for the setup steps.
