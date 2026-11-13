# Commands

How slash commands are built, registered, split across the two bots,
and gated by the custom permission system. This page is the
**architecture** reference — it does not list every command. For the
full per-command reference (every command, its options, and which bot
runs it), see the README's
[Systems](https://github.com/poos241/Discord-Testing-Bot-Grounds-V1#systems)
section. If a command is not in the README, it is not registered on
either bot.

## The live counts

Counts are the live Discord registrations, verified 2026-11-13
against the Discord API on both guilds — **the API is the source of
truth, not the code**. A bot can restart healthy and still have
commands that never went live, so always verify a new command in the
API (or in Discord) before calling it done.

| Bot | Top-level | Runnable slash commands |
| --- | --- | --- |
| Havenly Bot 2.0 (main) | 54 | 83 |
| Havenly Helper (worker) | 11 | 30 |
| Shared | 0 | 0 |

The main bot also has one user context-menu command,
**Check Introduction** (right-click a user → Apps). Five group names
are shared between the bots (`banlog`, `intro`, `modlogs`, `qotd`,
`watch`) but they are split by subcommand — zero runnable commands
are registered on both bots. See [Two bots](./two-bots.md) for the
split and why it exists.

## How a command is defined

Commands are pycord slash commands, organised into
**SlashCommandGroup** families (one group per system area) plus
standalone top-level commands. The structural rules:

- **Define groups at module level, never as cog methods.** A group
  defined inside a cog method does not survive the way pycord
  registers commands. Register a module-level group with
  `bot.add_application_command()` inside the package `setup()` that
  loads the cogs.
- **Register guild-scoped, not global.** Every command is registered
  with `guild_ids=GUILD_IDS` (the test server and Little Haven, in
  `config.py`). Global commands take up to an hour to propagate and
  are not what this bot wants. The one known exception is
  `/xp_event`, which is global while `/xp_event_end` is guild-scoped
  — that asymmetry is a quirk, not a pattern to copy.
- **Sync happens at startup, in `on_ready`.** The bot calls
  `sync_commands(force=True)` once it is ready. Commands only appear
  in Discord after a restart of the bot that owns them — and the
  Helper only syncs at startup, so inviting the Helper to a new
  guild needs a `havenly-helper` restart before its commands show up
  there (see [Two bots](./two-bots.md)).
- **The worker does not auto-sync.** pycord's `Bot.on_connect`
  auto-syncs with no guild arguments, which 403s for the Helper on
  guilds it has not joined and aborts the whole sync. The bot is
  created with `auto_sync_commands=not WORKER_MODE`, so the Helper
  relies on its explicit `on_ready` sync (to `client.guilds`) and
  the main bot keeps the default behaviour.
- **Answer Discord before slow work.** Defer the interaction before
  any database write or other slow work, or the command fails with
  "The application did not respond". If the reply must stay private,
  defer **ephemeral from the start** — a public defer locks the whole
  interaction public, and Discord ignores `ephemeral` on a later
  followup.

## Discord's hard limits

Check these before adding or changing a command — Discord rejects the
whole registration when one is broken, and the failure is silent from
the bot's side (the old commands keep working; the new ones never go
live):

- **100 guild application commands per guild, per bot.** The main bot
  is at 54 top-level, the Helper at 11 — plenty of headroom now, but
  count first. The bot hit this cap on 2026-11-11 (103 top-level,
  sync failed `400/30032`), and the fix was merging command families
  into groups (`/perm`, `/watch`, `/intro`, `/modlogs`, `/banlog`,
  `/auto_thread`, `/logs`) — 103 → 68, then the split took the main
  bot to 54. A merge or a removal is part of the plan for any new
  top-level command, not a later fix. Treat a sync failure with error
  400 code 30032 as a command-count failure.
- **25 choices per slash option.** Split a long picker into
  per-category subcommands instead of cutting useful options.
- **Required options before optional ones.** Discord rejects a
  command when a required option follows an optional one — check the
  exact command payloads the bot will send, not just that the code
  compiles. (This is why `/banlog delete`'s `confirm` is optional in
  the form but enforced in code.)
- **Modal labels at 45 characters or fewer.** Put examples and hints
  in the placeholder text, not the label.
- **10 attachments per slash command.** Attachment links expire after
  24 hours — re-host screenshots by re-uploading to a stored evidence
  channel instead of relying on the link.

Embed limits apply to command replies too: 6000 characters total
across all embeds in one message (send one embed per message when the
combined total would pass it), 1024 characters per embed field value
(chunk long lists across fields on line boundaries, never mid-line),
role mentions only in field values, never field names, and no
timestamps in embed footers.

## Which bot a command runs on

The split is **Option C: setup vs. use** (see
[Two bots](./two-bots.md)). The rule of thumb: if a command does
something *right now* for a member or a mod, it lives on the main
bot; if it *sets something up* or *runs a batch job*, it lives on the
Helper. All 24 level commands stay on the main bot.

The split is implemented two ways:

- **Cog level** — `bot.py` loads `COGS` in main mode and
  `WORKER_COGS` in worker mode (`WORKER_MODE=1`). Cogs that exist
  only on one bot (Backup, Permissions, ServerSettings on the
  Helper) are simply not in the other mode's list. `cogs.Logger`
  loads in **both** modes: its 8 listener cogs are gated to
  main-only, its `/logs` + `/log_toggle` commands go to the worker,
  and its prune loop is main-only.
- **Per-command gating** — a cog that has commands on both bots
  (Introduction, Modlogs, GHLog, WatchList, QOTD, Logger) wraps
  each command definition in a `WORKER_MODE` check at class level,
  so the command only exists on the class in the matching mode and
  only registers on that bot. The pattern is in
  `cogs/Introduction.py`. Background behaviour is gated the same
  way: the QOTD posting loop, the Logger prune loop, the WatchList
  `on_message` listener, and the Logger listeners are main-only;
  the timeout-board refresh + tempban sweep and the Backup daily
  snapshot are worker-only.

Two cache fixes make the split work live: Introduction config now
has a 60-second TTL (it used to cache forever, so a Helper-made
setup change would not reach the main bot until restart), and
WatchList reloads its store fresh from Postgres on every call (its
old boot-time cache plus full-table DELETE + re-insert save could
clobber the other bot's change). Other config reads were verified
live at the time of the split (Logger, QOTD, GHLog, board config,
`/perm` grants).

### Adding a command

1. Decide which bot it goes on **first** — real-time user/mod
   actions go on the main bot; setup/config and batch jobs go on
   the Helper. If a cog has commands for both bots, gate each
   command definition with a `WORKER_MODE` check at class level.
2. Add the cog to `COGS` in `bot.py` — or to `WORKER_COGS` if the
   cog belongs on the Helper.
3. **Count before you add a top-level command.** Discord caps guild
   application commands at 100 per guild. The main bot is at 54,
   the Helper at 11 — count first, and verify the sync actually
   registered the command (Discord API, not just a clean restart).
4. Restart the bot that owns the new command and check it shows up
   in Discord. (The Helper only syncs at startup.)

## Custom permissions

The custom permission system (`/perm`, on the Helper) can grant a
specific command to a specific role or user, **overriding** the
command's default Discord-permission gate. The rules:

- **REPLACE semantics** — a grant replaces the default Discord
  check for any command it covers; it does not add to it.
- **Server admins are always allowed.**
- **Precedence:** admin > user deny > user allow > role deny >
  role allow > default Discord check > deny when rules exist but
  don't match.
- Grants live in the shared `command_permissions` table in
  Postgres, so they apply to **both** bots — which is why the
  whole `/perm` group lives on the Helper while mods manage grants
  for every command (including main-bot commands) from there. A
  grant written by the Helper is visible to the main bot
  immediately, no restart.
- `/help` filters to only the commands the invoker can use
  (fail-closed — if you can't run a command, it doesn't show up).
  Because `/help` reads the bot's own registered command list,
  each bot's `/help` naturally shows only its own commands.

See [Permissions](./permissions.md) for the full system, and the
README's [Custom permissions](https://github.com/poos241/Discord-Testing-Bot-Grounds-V1#custom-permissions)
section for the command list.

## System overview

Every system, what it does, which bot runs it, and its command
groups. The per-command reference (options, who can run it) is in
the README's
[Systems](https://github.com/poos241/Discord-Testing-Bot-Grounds-V1#systems)
section — that is the canonical list.

| System | What it does | Bot | Command groups |
| --- | --- | --- | --- |
| Moderation | Time members out, purge a user's messages, look a member up, manage roles, rename users; owner-only process commands (`/restart_bot`, `/restart_web`, `/shutdown_bot`) | Main | `/timeout`, `/clear_user`, `/userinfo`, `/add_user_role`, `/remove_user_role`, `/rename_bot`, `/rename_user`, `/reset_user_name`, `/restart_bot`, `/restart_web`, `/shutdown_bot` |
| Timeout board | The "Active Timeouts" embed (soonest first, cap 25, "+N more"), refreshed on change and every 5 minutes | Helper | `/timeout_board` |
| Levels | Message/voice/game/daily XP, rank cards, leaderboard, role rewards, XP events — all 24 level commands | Main | `/level`, `/rank`, `/leaderboard`, `/daily`, `/cardcolor`, `/add_xp`, `/resetxp`, `/cleardata`, `/getxpsettings`, `/level_settings`, `/set_xp_rate`, `/set_cooldown`, `/set_level_channel`, `/set_level_role`, `/remove_level_role`, `/set_levelup_message`, `/toggle_levels`, `/toggle_level_messages`, `/toggle_thread_xp`, `/toggle_game_xp`, `/toggle_no_xp`, `/no_xp_bulk`, `/xp_event`, `/xp_event_end` |
| Eat It or Yeet It | Party game: vote Eat It or Yeet It on a food, majority wins | Main | `/eatyeet`, `/eatyeet_end`, `/eatyeet_leaderboard`, `/eatyeet_stats`, `/eatyeet_suggest`, `/eatyeet_history` |
| Question of the Day | Daily question, posted on schedule; members suggest, mods approve | Main, except config on Helper | `/qotd` (today, history, submit, post, skip, pending, approve, reject, remove) on Main; `/qotd config` on Helper |
| Introduction tracking | Tracks whether members posted an intro; role on intro; backfill scan | Main for checks, Helper for setup + scan | `/intro check` + `Check Introduction` (context menu) on Main; `/intro set_channel`, `set_role`, `settings`, `toggle`, `scan` on Helper |
| Modlogs | Searchable moderation-case record | Main for lookup, Helper for scan | `/modlogs list`, `recap`, `edit`, `actions` on Main; `/modlogs scan` on Helper |
| GitHub ban log | Logs bans/kicks to a GitHub Project board, with a second-mod approval step (a mod can never approve their own entry) | Main for logging, Helper for setup + batch jobs | `/banlog log`, `approve`, `update`, `delete` on Main; `/banlog set_channel`, `collect`, `backfill_cases` on Helper |
| Logger | Server event logging to per-category channels, 29 per-event toggles | Helper for config/toggles; main bot does the actual event logging | `/logs setup`, `change_channel`, `settings`; `/log_toggle message`, `member`, `voice`, `server`, `moderation` — all on Helper |
| Watch List | Logs a watched member's messages to a channel | Main, except channel setup on Helper | `/watch add`, `remove`, `add_id`, `remove_id`, `list`, `status`, `info`, `clear` on Main; `/watch set_channel` on Helper |
| Custom permissions | Per-command allow/deny grants (REPLACE semantics) | Helper | `/perm allow`, `remove`, `list`, `bulk`, `commands`, `overview`, `reset` |
| Bot settings | Read-only overview of every system's on/off state and key config | Helper | `/bot_settings` |
| Backup | Database snapshots (`pg_dump` + manifest, zipped); daily loop + manual commands | Helper | `/backup now`, `status` |
| Lockdown | Lock/unlock channels in a hurry, with auto-unlock timer | Main | `/lockdown lock`, `unlock`, `lockall`, `unlockall`, `slowmode`, `status` |
| Help & docs | In-Discord help, filtered to the commands you can use | Main | `/help`, `/show_tags`, `/show_categories`, `/diagnose_docs`, `/generate_tags` |
| Debug | Owner-only verbose logging + test command | Main | `/debug on`, `off`, `status`, `test` |

## Deliberately disabled cogs

Seven cogs are commented out in `bot.py` and their commands are
**not registered** on either bot. That is intentional (disabled
2026-11-12) — do not uncomment them, and do not expect their
commands to exist. Their files are still in `cogs/` for reference.

| Cog | Commands that do NOT exist |
| --- | --- |
| VoiceXP | `/voicexp optin`, `optout`, `status`, `leaderboard`, `config`, `setrate`, `setcap`, `enable`, `disable` |
| Tickets | `/ticket panel`, `config`, `show`, `open`, `close`, `reopen`, `claim`, `delete`, `add`, `remove`, `list` |
| Appeals | `/appeal submit`, `list`, `review`, `config`; `/modnotes search` |
| Automod | `/automod status`, `toggle`, `config` |
| AutoThreads | `/auto_thread`, `/set_auto_thread_channel`, `/remove_auto_thread_channel`, `/auto_thread_status` |
| TimeCmd | `/time` |
| CustomBadges | `/badge create`, `award`, `remove`, `delete`, `list` |

Note `/auto_thread` in particular: it appears in older docs and in
the 2026-11-11 merge history, but AutoThreads is disabled, so the
command is not registered. Likewise `/testbanlog` was deleted in the
2026-11-11 merge — it does not exist either.
