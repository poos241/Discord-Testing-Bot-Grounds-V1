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

The card doubles as a mini mod panel: **Warn**, **Timeout** (duration
like `10m`/`2h`/`1d`), **Kick**, **Ban** (with 0–7 days of message
deletion), **Clear**, and **Notes** buttons. Warn/Timeout/Kick/Ban
each open a form asking for a reason, then a confirm step with a
**DM them: Yes/No** toggle — the reason is only DM'd to the user if
you leave it on (with a note when their DMs are closed). The card
refreshes itself after every action, so there's no need to re-run
the command to see the new warn count, XP, or button states. Ban
flips to **Unban** and Timeout flips to **Remove timeout** when one
is already active.
Clear first shows a channel picker (plus an All-channels button),
then asks how many messages to delete or `all`. Notes keeps a
numbered per-user mod-notes list you can add to and remove from;
warns are counted on the card (stored in `data/mod_data.json`). The
**Watch** button adds the user to the watch list (asking for an
optional reason) or removes them if they're already on it — the
button flips to **Unwatch** when they're watched, and the card shows
who added them, when, and the reason. **Add XP** / **Remove XP**
buttons let you correct someone's XP by a set amount (adding runs
through the normal level-up path with role rewards). A `test_mode`
true/false option on the command simulates the actions without
applying them (the card footer shows when it's on), and a `private`
option (default on) keeps the card to yourself — turn it off to post
publicly. Only members with Manage Server / Administrator can press
the buttons (Timeout/Kick are disabled when the target isn't in the
server).
