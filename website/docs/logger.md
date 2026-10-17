# Logger internals

Source: `cogs/Logger/`. State: `data/message_log.db` (SQLite).

The Logger records server events to dedicated log channels — one channel
per category, configured per guild. It is separate from the Watch List
system (which mirrors watched users' messages); the Logger covers
server-wide events.

## Categories

| Category | Key | What's logged |
|---|---|---|
| Message | `message` | Message edits, deletes (with original content), bulk deletes |
| Member | `member` | Joins, leaves, kicks (via audit log), nickname/avatar changes, role adds/removes, voice joins/leaves/moves/mute/deafen |
| Server | `server` | Channel create/delete/rename/topic/slowmode, thread create/delete, emoji create/delete/rename, role create/delete/update, invite create/delete |
| Moderation | `moderation` | Bans, unbans, timeouts, message clears, user data wipes (moderator + reason from the audit log) |

## Package layout

| File | Role |
|---|---|
| `__init__.py` | `setup(bot)` — registers all six cogs |
| `config.py` | Category keys, embed colors, default channel names |
| `database.py` | SQLite: `messages` (message cache), `guild_logs` (per-guild channel config) |
| `logger.py` | `Logger.send(guild, category, embed)` — resolves the channel, swallows send errors |
| `base.py` | `BaseLogger` cog — every logger cog extends this for `send()` + `audit_entry()` |
| `embeds.py` | `LoggerEmbed` — shared embed builders (base, author, field, footer) |
| `messages.py` | `MessageLogger` — caches every message; logs edits/deletes |
| `members.py` | `MemberLogger` — joins, leaves, profile/role changes |
| `channels.py` | `ChannelLogger` — channel + thread events |
| `emoji.py` | `EmojiLogger` — emoji create/delete/rename |
| `moderation.py` | `ModerationLogger` — bans, unbans, timeouts |
| `commands.py` | `/setup_logs`, `/change_logchannel`, `/log_settings`, `/log_toggle` |
| `voice.py` | `VoiceLogger` — voice state changes |
| `invites.py` | `InviteLogger` — invite create/delete |
| `roles.py` | `RoleLogger` — role create/delete/update |
| `audit.py` | `Audit.latest()` — audit-log lookup matched by target ID |

## Commands

| Command | What it does | Who can use it |
|---|---|---|
| `/setup_logs` | Creates the 📜 Server Logs category + 4 staff-only log channels, wires them up | Administrator |
| `/change_logchannel` | Point one category at a different channel (picker for category + channel) | Administrator |
| `/log_settings` | Show which channel each category logs to, plus disabled events | Everyone |
| `/log_toggle message` | Toggle `message_edit`, `message_delete`, `bulk_delete` | Administrator |
| `/log_toggle member` | Toggle `member_join`, `member_leave`, `member_kick`, `nickname`, `avatar`, `role_member` | Administrator |
| `/log_toggle voice` | Toggle `voice_join`, `voice_leave`, `voice_move`, `voice_mute` | Administrator |
| `/log_toggle server` | Toggle channel/thread/emoji/role/invite events (13) | Administrator |
| `/log_toggle moderation` | Toggle `ban`, `unban`, `timeout` | Administrator |

## How sending works

Cogs never send directly. They build an embed with `LoggerEmbed` helpers
and call `self.send(guild, category, embed)` (from `BaseLogger`). That
goes through `Logger.send()`, which:

1. Looks up the channel ID from `guild_logs` for that guild + category.
2. Returns silently if none is configured (no setup = no logs, no errors).
3. Falls back to `bot.fetch_channel` if the channel isn't in cache.
4. Swallows `Forbidden` / `NotFound` / `HTTPException` — a deleted channel
   or lost permission never crashes an event handler.

## Message cache

`MessageLogger.on_message` stores every guild message in the `messages`
table. On delete, the logger prefers the live `Message` object but falls
back to the cached row, so deletes show the original content even for
uncached messages. Bulk deletes use `on_raw_bulk_message_delete` and log
a count.

## Audit log matching

`Audit.latest(guild, action, target_id)` fetches recent audit-log entries
for an action and returns the first one whose target matches `target_id`.
This keeps the "Moderator" / "Reason" fields on ban/timeout/channel
embeds accurate instead of grabbing an unrelated recent entry.

## Per-event toggles

Every log event has a toggle key (see `EVENT_GROUPS` in `config.py` —
29 events total). They default to on. `/log_toggle` is a command group
with per-category subcommands (`/log_toggle voice`, etc.) because Discord
caps option choices at 25 — one flat list wouldn't fit. Each subcommand flips one;
`db.is_enabled(guild_id, key)` is checked at the top of every handler,
and `/log_settings` lists what's currently disabled. The state lives in
the `log_toggles` table, keyed by `(guild_id, event_key)`.

## Kick detection

`on_member_remove` can't tell a kick from a leave on its own, so it
checks the audit log for a `kick` entry targeting that user within the
last 15 seconds. Kicks go to the 🚨 moderation channel as
"👢 Member Kicked" (with moderator + reason); plain leaves stay in 👥.

## Gotchas

- **Message Content intent.** The Logger needs the privileged Message
  Content intent to see message text. It's set in `bot.py`
  (`intents.message_content = True`) and must also be toggled on in the
  Discord Developer Portal (Bot → Privileged Gateway Intents), or all
  logged content will be empty.
- **Two `on_member_update` listeners.** `MemberLogger` (nick/avatar/roles)
  and `ModerationLogger` (timeouts) both listen; they check disjoint
  conditions, so nothing double-logs.
- **Setup is per guild.** Each server runs `/setup_logs` once; the config
  lives in `guild_logs`, keyed by `(guild_id, log_type)`.
