# Commands

Every slash command (and the one context-menu command) in the bot, built from the actual code — **127 slash commands + 1 user context-menu command = 128 commands**. See the README's [Complete command reference](https://github.com/poos241/Discord-Testing-Bot-Grounds-V1#-complete-command-reference) for the same list with full options. Commands are guild-scoped to `GUILD_IDS` in `config.py` unless the Scope column says **Global**.

## admin_cog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/timeout` | Times out a member, with a preset length or a free-form duration (max 28d); asks to replace if they already have an active timeout. | `member` (Member, required); `preset` (optional; Light—5m, Short—15m, Medium—1h, Long—1d, Extended—1w, Severe—2w); `duration` (optional string, e.g. `1h30m`); `reason` (optional, default "No reason given") | Manage Server / Admin (in-callback `_is_manager`) | Guild |
| `/timeout_board` | Posts, moves, shows, or removes the "Active Timeouts" board (lists every active Discord timeout and tempban, soonest expiry first, auto-refreshing). | `channel` (TextChannel, optional — where to post/move the board); `remove` (bool, optional, default false) | Manage Server / Admin (in-callback `_is_manager`) | Guild |
| `/clear_user` | Deletes a user's messages in one channel or all channels. | `target_user` (User, optional); `user_id` (string, optional, for users who left); `channel` (TextChannel, optional); `amount` (int, optional, default 100) | Administrator | Global |
| `/userinfo` | Shows a detailed user card with a self-updating mini mod panel (see panel paragraph at the end). | `member` (Member, optional); `user` (string, optional — user ID, mention, or username); `private` (bool, optional, default true — only you see the card); `test_mode` (bool, optional, default false — simulates actions) | Administrator | Guild |
| `/remove_user_role` | Removes a role from a user. | `member` (Member, required); `role` (Role, required) | Administrator | Global |
| `/add_user_role` | Gives a role to a user. | `member` (Member, required); `role` (Role, required) | Administrator | Global |
| `/rename_bot` | Changes the bot's nickname in the server. | `new_nick` (string, required) | Administrator | Global |
| `/rename_user` | Changes a user's nickname. | `member` (Member, required); `new_nick` (string, required) | Administrator | Global |
| `/reset_user_name` | Clears a user's nickname (removes the custom nickname). | `member` (Member, required) | Administrator | Global |
| `/shutdown_bot` | Shuts the bot down (stays down until restarted). | none | Bot owner only | Global |
| `/restart_bot` | Restarts the bot. | none | Bot owner only | Global |

## fun_cog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/eatyeet` | Starts a round of Eat It or Yeet It. | `duration` (int, optional, default 30s; choices: 30s, 1h, 2h, 4h, 8h, 12h, 24h); `source` (string, optional, default auto; Auto = mix of API + local, Local list only, API only) | No gate (everyone) | Guild |
| `/eatyeet_end` | Ends the active round in this channel early. | none | Round starter or Administrator (in-callback) | Guild |
| `/eatyeet_leaderboard` | Shows the top 10 players by points. | none | No gate (everyone) | Guild |
| `/eatyeet_stats` | Shows a player's rounds played, points, majority-vote rate, and streaks. | `user` (User, optional — defaults to you) | No gate (everyone) | Guild |
| `/eatyeet_suggest` | Suggests a food for the community pool (credited to you). | `food` (string, required, 3–100 chars) | No gate (everyone) | Guild |
| `/eatyeet_history` | Shows the last 10 finished rounds with foods and verdicts. | none | No gate (everyone) | Guild |

## Level_system

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/set_xp_rate` | Sets the min/max XP gained per message. | `minimum` (int, required); `maximum` (int, required) | Administrator | Guild |
| `/set_cooldown` | Sets the cooldown in seconds between XP gains per user (0 = no cooldown). | `seconds` (int, required) | Administrator | Guild |
| `/set_level_channel` | Sets the channel where level-up messages are posted. | `channel` (TextChannel, required) | Administrator | Guild |
| `/level` | Shows your (or another member's) level and XP progress. | `member` (Member, optional) | No gate (everyone) | Guild |
| `/leaderboard` | Shows the top 10 users by level and XP. | none | No gate (everyone) | Guild |
| `/add_xp` | Adds XP to a user (level-ups are announced like normal). | `member` (Member, required); `amount` (int, required) | Administrator | Guild |
| `/resetxp` | Resets a user's XP to 0 and level to 1. | `member` (Member, required) | Administrator | Guild |
| `/cleardata` | Clears all level data for this server. | none | Administrator | Guild |
| `/getxpsettings` | Shows the server's XP settings (rate, cooldown, level-up channel/message, role rewards, no-XP channels, XP events, game XP toggle). | none | No gate (everyone) | Guild |
| `/set_level_role` | Sets a role reward for reaching a level (cumulative). | `level` (int, required); `role` (Role, required) | Administrator | Guild |
| `/remove_level_role` | Removes a level's role reward (members who already have it keep it). | `level` (int, required) | Administrator | Guild |
| `/toggle_game_xp` | Toggles level XP earned by voting in Eat It or Yeet It (on by default). | none | Administrator | Guild |
| `/toggle_no_xp` | Toggles message XP on/off for a channel. | `channel` (TextChannel, required) | Administrator | Guild |
| `/xp_event` | Starts a server-wide bonus XP multiplier event (multiplier 2–5). | `minutes` (int, required); `multiplier` (int, optional, default 2) | Administrator | **Global** (no `guild_ids=` — the only Level command that is global) |
| `/xp_event_end` | Ends a running XP event early. | none | Administrator | Guild |
| `/daily` | Claims your daily XP bonus (once every 20h; consecutive-day streaks earn more). | none | No gate (everyone) | Guild |
| `/cardcolor` | Sets your rank/level-up card accent color (hex, preset name, or `reset`). | `color` (string, required) | No gate (everyone) | Guild |
| `/set_levelup_message` | Sets a custom level-up announcement (`{user}`, `{name}`, `{level}`); run with no text to reset to default. | `message` (string, optional) | Administrator | Guild |
| `/rank` | Shows your rank card image (level, XP progress, server rank). | `member` (Member, optional) | No gate (everyone) | Guild |

## VoiceXP

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/voicexp optin` | Opts you in to earning XP for time in voice channels (needs 1+ other non-bot person; muted/deafened/AFK time never counts). | none | No gate (everyone) | Guild |
| `/voicexp optout` | Opts you out of voice XP (banked totals are kept). | none | No gate (everyone) | Guild |
| `/voicexp status` | Shows your (or another member's) voice XP stats (opt-in state, total voice time/XP, today's cap progress). | `member` (Member, optional) | No gate (everyone) | Guild |
| `/voicexp leaderboard` | Shows the top 10 by total qualifying voice time (with voice XP). | none | No gate (everyone) | Guild |
| `/voicexp config` | Shows the server's voice XP settings (enabled state, rate, cap, opt-in count). | none | Administrator | Guild |
| `/voicexp setrate` | Sets XP earned per minute of voice time (1–10, default 1). | `rate` (int, required) | Administrator | Guild |
| `/voicexp setcap` | Sets the daily voice XP cap per user (0 = no cap, default 100 XP per UTC day). | `cap` (int, required) | Administrator | Guild |
| `/voicexp enable` | Enables voice XP for this server. | none | Administrator | Guild |
| `/voicexp disable` | Disables voice XP for this server (banked totals and opt-ins are kept). | none | Administrator | Guild |

## WatchList

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/watch_add` | Adds a user to the watch list (their messages are logged to the watch channel). | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_remove` | Removes a user from the watch list. | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_add_id` | Adds a user to the watch list by Discord ID (or mention). | `user_id` (string, required) | Manage Server / Admin | Global |
| `/watch_remove_id` | Removes a user from the watch list by Discord ID. | `user_id` (string, required) | Manage Server / Admin | Global |
| `/watch_list` | Shows everyone on the watch list. | none | Manage Server / Admin | Global |
| `/watch_status` | Shows watch-list status (user count, log channel, logging state). | none | Manage Server / Admin | Global |
| `/watch_info` | Shows details about one watched user (who added them and when). | `user` (Member, required) | Manage Server / Admin | Global |
| `/watch_set_channel` | Sets the channel where watched users' messages are logged. | `channel` (TextChannel, required) | Manage Server / Admin | Global |
| `/watch_clear` | Removes everyone from the watch list (with confirmation; already-sent logs are kept). | none | Manage Server / Admin | Global |

## DebugCog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/debug on` | Enables debug logging (persists via `data/.debug_enabled`). | none | Administrator or Manage Server | Guild |
| `/debug off` | Disables debug logging. | none | Administrator or Manage Server | Guild |
| `/debug status` | Shows whether debug mode is on or off. | none | Administrator or Manage Server | Guild |
| `/debug test` | Prints a test debug line to the console + `data/debug.log`. | none | Administrator or Manage Server | Guild |

## QOTD

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/qotd today` | Shows today's Question of the Day. | none | No gate (everyone) | Guild |
| `/qotd history` | Looks back at past Questions of the Day. | `count` (int, optional, default 7, 1–25) | No gate (everyone) | Guild |
| `/qotd submit` | Submits a question for a future QOTD (10–500 characters). | `question` (string, required) | No gate (everyone) | Guild |
| `/qotd post` | Posts today's question right now. | none | Manage Messages / Admin | Guild |
| `/qotd skip` | Replaces today's question with a fresh one. | none | Manage Messages / Admin | Guild |
| `/qotd config` | Sets the QOTD channel, post time, timezone, or on/off. | `channel` (TextChannel, optional); `post_time` (string, optional, HH:MM 24-hour); `timezone` (string, optional, autocomplete); `enabled` (bool, optional) | Manage Messages / Admin | Guild |
| `/qotd pending` | Lists submitted questions waiting for approval. | none | Manage Messages / Admin | Guild |
| `/qotd approve` | Approves a submitted question into the rotation. | `question_id` (int, required — the pending question's #id) | Manage Messages / Admin | Guild |
| `/qotd reject` | Rejects a submitted question. | `question_id` (int, required) | Manage Messages / Admin | Guild |
| `/qotd remove` | Removes a question from this server's rotation. | `question_id` (int, required — from history or a post) | Manage Messages / Admin | Guild |

## Tickets

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/ticket panel` | Posts the ticket panel in this channel (members click it to open a ticket). | none | Manage Messages / Admin | Guild |
| `/ticket config` | Sets the ticket settings for this server. | `staff_role` (Role, optional); `category` (CategoryChannel, optional); `log_channel` (TextChannel, optional); `panel_channel` (TextChannel, optional) | Manage Messages / Admin | Guild |
| `/ticket show` | Shows the ticket settings for this server. | none | Manage Messages / Admin | Guild |
| `/ticket open` | Opens a support ticket (one open ticket per user). | `topic` (string, optional) | No gate (everyone) | Guild |
| `/ticket close` | Closes this ticket. | `reason` (string, optional) | Ticket opener or staff | Guild |
| `/ticket reopen` | Reopens this closed ticket. | none | Ticket opener or staff | Guild |
| `/ticket claim` | Claims (or releases) this ticket. | none | Staff only | Guild |
| `/ticket delete` | Deletes this closed ticket's channel (only works on closed tickets). | none | Staff only | Guild |
| `/ticket add` | Adds a member to this ticket channel. | `member` (Member, required) | Staff only | Guild |
| `/ticket remove` | Removes a member from this ticket channel (cannot remove the opener). | `member` (Member, required) | Staff only | Guild |
| `/ticket list` | Lists this server's open tickets. | none | Manage Messages / Admin | Guild |

## Backup

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/backup now` | Takes a backup snapshot right now. | none | Manage Messages / Admin | Guild |
| `/backup status` | Shows the latest backup snapshot. | none | Manage Messages / Admin | Guild |

## Appeals

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/appeal submit` | Appeals a ban or timeout. (In DMs it redirects you to DM the bot the word `appeal`.) | `appeal_type` (string, required; choices: `ban`, `timeout`); `details` (string, required, max 1000 chars) | No gate (everyone); one pending appeal per user | Guild |
| `/appeal list` | Lists appeals, newest first (max 20 shown). | `status` (string, optional, default `pending`; choices: `pending`, `approved`, `denied`, `all`) | Appeal staff (configured staff role, else Manage Messages / Admin; Admins always pass) | Guild |
| `/appeal review` | Reviews one appeal (shows it with Approve/Deny buttons). | `appeal_id` (int, required — appeal number, e.g. 3) | Appeal staff (same as above) | Guild |
| `/appeal config` | Sets the appeals channel / staff role (run with no options to view current settings). | `channel` (TextChannel, optional); `staff_role` (Role, optional) | Manage Server / Admin | Guild |
| `/modnotes search` | Keyword search across mod notes, warns, and cases. | `keyword` (string, required); `user` (Member, optional — only search this member's records) | Manage Messages / Admin | Guild |

## Lockdown

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/lockdown lock` | Locks a channel so @everyone cannot send messages (restores the previous permission on unlock); a duration sets a timed lock that auto-unlocks. | `channel` (TextChannel, optional — defaults to current channel); `duration` (int, optional — minutes); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown unlock` | Unlocks a channel, restoring its previous @everyone permission. | `channel` (TextChannel, optional — defaults to current channel) | Manage Channels | Guild |
| `/lockdown lockall` | Locks every text channel in the server (skips forum channels and channels already bot-locked). | `duration` (int, optional — minutes); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown unlockall` | Unlocks every channel the bot has locked in this server. | none | Manage Channels | Guild |
| `/lockdown slowmode` | Sets slowmode on a channel (0 turns it off). | `seconds` (int, required, 0–21600); `channel` (TextChannel, optional — defaults to current channel); `reason` (string, optional) | Manage Channels | Guild |
| `/lockdown status` | Shows every channel the bot currently has locked, with pending auto-unlocks. | none | Manage Channels | Guild |

## Automod

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/automod status` | Shows the automod rules and spam settings for this server. | none | Manage Messages | Guild |
| `/automod toggle` | Turns one automod rule on or off (leave `enabled` blank to flip it). | `rule` (string, required — `spam`, `invites`, `external_links`, `caps`); `enabled` (bool, optional) | Manage Messages | Guild |
| `/automod config` | Sets the spam burst threshold and window. | `threshold` (int, optional, 1–50); `window` (int, optional, 5–300 seconds) | Manage Messages | Guild |

## AutoThreads

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/auto_thread` | Toggles auto-threads for the channel the command is run in (default 24h archive, no name prefix; does not work in threads or DMs). | none | Manage Channels | Guild |
| `/set_auto_thread_channel` | Designates a channel for auto-threads, or updates its settings. | `channel` (TextChannel, required); `archive_minutes` (int, optional — 60, 1440, 4320, or 10080; blank keeps current); `name_prefix` (string, optional — text put in front of every thread name) | Manage Channels | Guild |
| `/remove_auto_thread_channel` | Stops auto-threading a channel (existing threads are left alone). | `channel` (TextChannel, required) | Manage Channels | Guild |
| `/auto_thread_status` | Lists every channel designated for auto-threads, with archive setting and name prefix. | none | Manage Channels | Guild |

## TimeCmd

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/time` | Shows a member's local time from their profile timezone (blank = yourself; someone else's time only shows if they opted in to sharing local info). | `user` (Member, optional) | No gate (everyone) | Guild |

## CustomBadges

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/badge create` | Creates a custom badge for this server (name becomes its per-server slug). | `name` (string, required); `icon` (string, optional, default medal emoji); `description` (string, optional — tooltip text) | Manage Messages | Guild |
| `/badge award` | Awards a custom badge to a member (appears on their profile badge shelf + activity feed). | `badge_ref` (string, required, autocomplete — badge name/slug); `member` (Member, required) | Manage Messages | Guild |
| `/badge remove` | Revokes a member's custom badge (the badge definition stays). | `badge_ref` (string, required, autocomplete); `member` (Member, required) | Manage Messages | Guild |
| `/badge delete` | Deletes a custom badge and all of its awards (cannot be undone). | `badge_ref` (string, required, autocomplete) | Manage Messages | Guild |
| `/badge list` | Lists this server's custom badges and award counts. | none | Manage Messages | Guild |

## GHLog

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/testbanlog` | Posts a clearly-marked TEST draft item to the test GitHub project (proves the bot can reach GitHub Projects). | none | Administrator | Guild |
| `/banlog` | Logs a ban or kick to the GitHub ban-log project (preview + confirm first; nothing posts until confirmed). | `action` (string, required; choices: `Ban`, `Kick`); `reason` (string, required); `member` (Member, optional — pick if still in server); `user_id` (string, optional — ID, mention, or username if they left); `status` (string, optional; choices: `Preds`, `Intolerance e.g. transphobia, racism etc`, `Trolls/Bullies`, `Advertisers/Scammers`, `Misc`); `tags` (string, optional; choices: `more info`, `Blacklist approved`); `evidence` (string, optional — links separated by spaces); `screenshot` (Attachment, optional) | Manage Server / Admin (in-callback) | Guild |
| `/banlog_update` | Updates the most recent logged case for a user (Status and/or tags, and/or appends a dated note). | `member` (Member, optional); `user_id` (string, optional); `status` (string, optional; same choices as /banlog); `tags` (string, optional; same choices); `note` (string, optional) | Manage Server / Admin (in-callback) | Guild |
| `/banlog_delete` | Deletes the most recent logged case for a user (type `DELETE` exactly to confirm; cannot be undone). | `member` (Member, optional); `user_id` (string, optional); `confirm` (string, optional in the form but enforced in code — anything other than `DELETE` refuses; kept optional because Discord rejects a command when a required option follows optional ones) | Manage Server / Admin (in-callback) | Guild |

## Introduction

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/intro_set_channel` | Sets the introductions channel (and optional log channel). | `channel` (TextChannel, required); `log_channel` (TextChannel, optional) | Manage Server / Admin | Guild |
| `/intro_set_role` | Sets the role given to members who post an introduction. | `role` (Role, required) | Manage Server / Admin | Guild |
| `/intro_settings` | Shows the introduction tracking setup for this server. | none | Manage Server / Admin | Guild |
| `/intro_toggle` | Turns an introduction tracking behaviour on or off (leave `value` blank to flip it). | `setting` (string, required; choices: `auto_assign_role`, `auto_remove_role`, `scan_on_message`); `value` (bool, optional) | Manage Server / Admin | Guild |
| `/intro_scan` | Scans the intro channel and marks everyone who already posted (up to 1000 recent messages). | `limit` (int, optional, default 100, 1–1000); `add_role` (bool, optional, default true) | Manage Messages / Admin | Guild |
| `/intro_check` | Checks whether a member has posted an introduction. | `member` (Member, optional); `user_id` (string, optional — raw user ID for members who left) | Manage Messages / Admin | Guild |
| **Check Introduction** (user context-menu command — right-click a user → Apps) | Same check as `/intro_check` for that member. | (the clicked user) | Manage Messages / Admin | Guild |

## Modlogs

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/modlogs` | Browses moderation cases, newest first (filter by user, type, or date). | `member` (Member, optional); `user_id` (string, optional — raw ID for users who left); `type` (string, optional; choices: `warn`, `timeout`, `untimeout`, `kick`, `ban`, `tempban`, `unban`, `clear`, `strip_roles`, `wipe`); `before` (string, optional — only cases before YYYY-MM-DD); `after` (string, optional — only cases from YYYY-MM-DD) | Manage Server / Admin | Guild |
| `/modlogs_recap` | Counts by action type, most recent case, and tempban status for one user. | `member` (Member, optional); `user_id` (string, optional) | Manage Server / Admin | Guild |
| `/modlogs_edit` | Picks one of a user's recent cases to edit its reason or delete it. | `member` (Member, optional); `user_id` (string, optional) | Manage Server / Admin | Guild |
| `/mod_actions` | Lists every moderation action performed by one moderator. | `moderator` (Member, required) | Manage Server / Admin | Guild |

## Logger

| Command | What it does | Options | Who can run it | Scope |
|---|---|---|---|---|
| `/setup_logs` | Creates the log channels and configures the Logger system. | none | Administrator (`@commands.has_permissions(administrator=True)`) | Guild |
| `/change_logchannel` | Points one log category at a different channel. | `log_type` (string, required; choices: `message`, `member`, `server`, `moderation`); `channel` (TextChannel, required) | Administrator (in-callback) | Guild |
| `/log_settings` | Shows the Logger configuration (which channel each category logs to + disabled events). | none | **No gate — anyone can run it** (ephemeral reply) | Guild |
| `/log_toggle message` | Toggles message event logging. | `event` (string, required; choices: `message_edit`, `message_delete`, `bulk_delete`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle member` | Toggles member event logging. | `event` (string, required; choices: `member_join`, `member_leave`, `member_kick`, `nickname`, `avatar`, `role_member`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle voice` | Toggles voice event logging. | `event` (string, required; choices: `voice_join`, `voice_leave`, `voice_move`, `voice_mute`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle server` | Toggles server event logging. | `event` (string, required; choices: `channel_create`, `channel_delete`, `channel_update`, `thread_create`, `thread_delete`, `emoji_create`, `emoji_delete`, `emoji_rename`, `role_create`, `role_delete`, `role_update`, `invite_create`, `invite_delete`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
| `/log_toggle moderation` | Toggles moderation event logging. | `event` (string, required; choices: `ban`, `unban`, `timeout`); `enabled` (bool, required) | Administrator (in-callback) | Guild |
