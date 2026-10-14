# Watch List internals

Source: `cogs/WatchList.py`. State: `data/watchlist_data.json`
(via `config.load_json` / `save_json`).

## What it does

Moderators put users on a per-server watch list. Every message a watched
user sends is mirrored to a configured log channel as an embed (author,
channel, timestamps, content, attachments, stickers, jump link). The
system is intentionally separate from the main Logger.

## Commands

All commands require **Manage Server** or **Administrator** (via the
`@watch_admin()` check decorator — broader than the bot-wide
`@admin_required()`, which is Administrator-only).

| Command | What it does | Who can use it |
|---|---|---|
| `/watch_add` | Add a user via the member picker | Manage Server / Admin |
| `/watch_remove` | Remove a user via the member picker | Manage Server / Admin |
| `/watch_add_id` | Add by raw Discord ID (works when the picker is awkward) | Manage Server / Admin |
| `/watch_remove_id` | Remove by raw Discord ID | Manage Server / Admin |
| `/watch_list` | Show everyone watched + log channel status | Manage Server / Admin |
| `/watch_status` | System status: count, channel, logging state | Manage Server / Admin |
| `/watch_info` | Who added a watched user, and when | Manage Server / Admin |
| `/watch_set_channel` | Set the log channel | Manage Server / Admin |
| `/watch_clear` | Remove everyone (button confirmation) | Manage Server / Admin |

Every command carries `@extra_help(...)`, so they appear in the bot's
help system like every other command.

## Code patterns

**One record builder.** Both add paths use `_user_record(member,
added_by)` — the stored dict shape (`user_id`, `username`,
`display_name`, `added_by`, `added_by_name`, `added_at`) is defined in
exactly one place.

**One ID parser.** `_parse_user_id()` handles raw IDs and `<@...>`
mentions for both `_id` commands; `_resolve_member()` does the
cache-then-API member lookup with `NotFound` / `Forbidden` handling.

**One chunker.** `_chunk_lines()` splits long user lists into
≤1000-char embed fields; shared by `/watch_list` and `/watch_status`
(Discord caps fields at 1024 chars).

**Permission as a decorator.** Instead of calling a check helper inside
every command body, `@watch_admin()` is a `commands.check` — denied
users get one consistent ephemeral reply, and the command body stays
focused.

## The log loop

`on_message` bails out fast: DMs → bots → not watched → no log channel
→ message is in the log channel itself. Only then does it build the
embed. `AllowedMentions.none()` on the send keeps watched users'
`@everyone` attempts from pinging the log channel.

## `/userinfo` crossover

`/userinfo` (in `admin_cog.py`) reads the same JSON file to show
whether a user is on the watch list, alongside their server XP (from
the level system's `get_levels`) and ban status (via
`guild.fetch_ban`). Give it a member pick, or type a user ID, mention,
or username — an ID also works for users who left or are banned.
