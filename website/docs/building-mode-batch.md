# Building-mode batch (October 2026)

Eighteen systems and fixes built in one batch (27–28 October 2026),
developed locally on the bot host and pushed together. Each section names
the files, the commands or pages, the behavior, and the known limits.
All slash commands are guild-scoped unless noted. The batch did not
change the README's setup flow — see the README's batch section for the
user-facing summary.

## 1. Notifications: clear everything + improvements

**Files:** `web/blueprints/notifications.py`, `web/templates/base.html`,
`data/notification_read.json` (shape change only).

Notifications are recomputed from their sources (mod cases + level-ups),
so "clearing" stores dismissed IDs instead of deleting rows. The read
file is now a per-user object `{read_ts, read[], unread[], dismissed[]}`
(old bare-int watermarks migrate on read; lists cap at 500).

**Endpoints:** `POST /api/notifications/dismiss`, `/mark`, `/clear`
(scope `all|read`); `GET` adds a per-item `type` (`mod`/`level`).

**UI:** filter tabs All/Mod/Level-ups, per-item × + Mark read/unread,
footer Clear read + Clear all (red, `confirm()` gate), empty state
"You're all caught up 🎉". The old Mark-all-read wiped dismissals; it no
longer does. Clear all is un-undoable, and the badge counts unread
among the newest 30 only (pre-existing).

## 2. Question of the Day (QOTD)

**Files:** `cogs/QOTD.py`, new tables `qotd_questions`, `qotd_config`,
`qotd_history`, `qotd_guild_exclusions`. Registered in `bot.py` COGS
and `config.py` COMMAND_TAGS.

**Commands:** `/qotd today|history|submit|post|skip|config|pending|
approve|reject|remove`. Mod gate is Manage Messages or Administrator
(local `is_mod`).

**Behavior:** a 1-minute `tasks.loop` scheduler posts one safe-for-work
question a day (default 09:00, `America/Chicago`, per-guild channel/time/
timezone/enabled config). Posts get a daily thread `QOTD - <date>` with
24h auto-archive; the post survives a thread failure. 60 seed questions;
global pool + per-guild history/exclusions; no repeats until exhausted,
then least-recent first. Missed-day catch-up runs within a minute of
startup and never double-posts (the history row is the guard).

**Notes:** no usable free QOTD API exists (trivia APIs are quizzes), so
the pool is local by design; `fetch_external_question()` is a stub
extension point. No dashboard hook or XP/streak tie-ins. Timezone names
need the `tzdata` package — it was missing on the host, which made
*every* zone reject; `tzdata` is now in `requirements.txt`, and the
config timezone option has a 54-zone autocomplete (free text still
accepts any valid IANA zone).

## 3. Ticket system (new, from the ground up)

**Files:** `cogs/Tickets.py`, new tables `ticket_guild_config`,
`support_tickets`. The old ticket cog was not salvaged and its legacy
tables were left untouched.

**Commands:** `/ticket panel|config|show|open|close|reopen|claim|
delete|add|remove|list`. Panel button + topic modal; per-server
numbering; one open ticket per user; close locks/renames/logs and leaves
Reopen/Delete buttons (no auto-delete). Staff is the configured role,
or Manage Messages/Admins as fallback. Views are persistent
(`tickets:panel_open`, `tickets:close`, `tickets:claim`,
`tickets:reopen`).

**Gotcha fixed after shipping:** `Tickets.__init__` registered views
during `load_extension`, but `discord.ui.View.__init__` needs a running
event loop — the bot crashed on startup with `no running event loop`.
Views now register once in `on_ready` (guarded against reconnects).
Config saves merge with the existing row so partial updates can't reset
`next_number`. Closed tickets keep opener read access; fully hiding them
is a one-line change if wanted.

## 4. Unified backup + restore

**Files:** `utils/backup.py`, `cogs/Backup.py`,
`web/blueprints/backups.py`, `web/templates/backups.html`. No models.py
table — the registry lives in the zip manifests so it survives the
disaster it is meant to recover from.

**Behavior:** daily snapshot at 04:00 host-local (`tasks.loop`,
`BACKUP_DAILY_HOUR` override) plus `/backup now|status` (Manage Messages/
Admin) and a mod-only `/backups` web page (manual snapshot, download,
delete, restore). Each snapshot is one zip in `data/backups/`
(`<YYYYMMDD-HHMMSS>_<label>.zip`) with `bot.db` + `message_log.db`
(via the SQLite backup API, consistent while running) + the legacy JSON
files (`mod_data`, `watchlist`, 4 eatyeet files — the rollback copies)
+ `manifest.json` (sizes + SHA-256). Retention: newest 14 daily + 10 manual/pre-restore. Excluded:
`notification_read.json`, `profiles.json.migrated`.

**Restore:** hash-verifies first, takes an automatic pre-restore safety
snapshot, restores via the backup API + atomic JSON replace, then tells
the mod to restart. **Warning: restore overwrites live data — never
test it casually on a live database.**

## 5. Appeals + mod notes search

**Files:** `cogs/Appeals.py`, new tables `appeal_guild_config`,
`appeals`, storage helpers. `admin_cog` ban/timeout DMs now mention
appeals.

**Commands:** `/appeal submit` (in-server, or DM the bot `appeal` for a
modal), `/appeal list`, `/appeal review <id>` with Approve/Deny buttons
(approve lifts the ban/timeout + records a case + DMs the appellant;
deny records a reason + DMs the outcome). Appeals post to the configured
appeals channel. `/modnotes search <keyword> [user]` searches the
`mod_data` table (SQLite) for notes/warns/cases server-wide.

**Limits:** the review view is non-persistent — buttons may die across a
restart, so re-run `/appeal review`. No web review page yet, and no
re-appeal-after-denial policy yet.

## 6. JSON → SQLite migration (finished)

**Files:** `utils/json_sqlite_store.py`, 7 new tables in `models.py`,
`config.py` redirects, `profiles.py` `_load_eatyeet` uses the store.

Six JSON files moved to SQLite: `mod_data`, `watchlist_data`,
`eatyeet_stats`, `eatyeet_suggestions`, `eatyeet_active`,
`eatyeet_rematch`. Migration is **lazy**: the first load/save after
restart imports the JSON to SQLite; the original JSONs stay untouched as
rollback (rollback = restore the pre-migration code + JSON backups).
Profiles migrated earlier the same way. New code should use the store
helpers, not `config.load_json`, for these datasets. See
[data-layer](./data-layer.md) for the current split.

## 7. Back-to-top button fix

**Files:** `web/templates/base.html` only (32,082 → 32,769 bytes).

The back-to-top button moved from bottom-right to bottom-left
(`left: 24px; bottom: 24px`; ≤640px: `left: 16px`, bottom
`calc(16px + env(safe-area-inset-bottom))`) so it no longer overlaps
the debug button. The debug FAB/panel stay at bottom-right, untouched.

## 8. Friend system (web)

**Files:** `web/blueprints/friends.py` (registered in the app factory),
tables `friendships` + `friend_settings`, storage helpers, Friends
sections on own + public profile pages, bell items.

**Behavior:** mutual only (request → accept); one row per pair; declined
rows are preserved and reopened on a new request; unfriend/cancel delete
the row. Requests require a shared server (guild cache, member-fetch
fallback; on check failure it allows and the recipient can decline).
Self-requests and non-numeric IDs are blocked.

**Profile display:** own `/profile` shows a Friends section (links to
`/profile/<id>`), pending incoming Accept/Decline, pending outgoing
Cancel, and an add-by-ID form. Public `/profile/<id>` shows only friends
who are themselves public; private friends are never exposed. Logged-in
non-owners get Add/Cancel/Pending/Unfriend via
`/api/friends/status/<id>`; logged-out viewers see no action area.

**Opt-out toggle** (on `/profile/edit`): turning it ON blocks new
requests AND auto-declines all pending incoming (count returned);
turning it OFF does not resurrect declined rows; outgoing pending
requests are unaffected. Bell: pending requests appear as `friend` items
(👋, sender name cached at request time) with Accept/Decline;
dismiss/mark-read hides the bell item only and does NOT decline.

**Left out:** no extra "hide friends" toggle, no discovery beyond
add-by-ID + public-profile buttons, no notification to the sender on
accept/decline.

## 9. Voice time XP + VC leaderboard

**Files:** `cogs/VoiceXP.py`, tables `voice_xp_config` +
`voice_xp_users`, storage helpers. Registered in `bot.py` COGS and
`config.py` tags.

**Commands:** `/voicexp optin|optout|status|leaderboard` (top 10 by
minutes + voice XP) plus admin `config|setrate|setcap|enable|disable`.

**Behavior:** a 1-minute ticker awards 1 XP per qualifying minute,
banked in 5-minute chunks via `award_xp`. A minute qualifies when the
user opted in, at least one other non-bot person is present, and the
user is not muted/deafened/server-muted/server-deafened and not in the
AFK channel. Stage channels are excluded. Defaults: 1 XP/min, 100 base
XP/day cap (UTC day; event multipliers apply on top). The leaderboard
is Discord-only; the web view is the live VC viewer below.

**Limit:** unbanked minutes live in memory only and are lost on restart
(≤5 min).

**Hotfix 2026-10-28:** `/voicexp optin` crashed on first use with
`IntegrityError: NOT NULL constraint failed: voice_xp_users.total_minutes`.
The user-row saver built values with `payload.get()` (explicit `None`
for missing columns) and then called `setdefault()`, which only fills
*absent* keys — so `total_minutes` stayed `NULL`. The saver now drops
`None` values before applying defaults; the same fix went into the
lockdown and auto-thread savers, which shared the pattern.

## 10. Lockdown + slowmode

**Files:** `cogs/Lockdown.py`, table `lockdown_channels`, storage
helpers. Registered in `bot.py` COGS and `config.py` tags.

**Commands:** `/lockdown lock|unlock|lockall|unlockall|slowmode|status`,
all gated with `Manage_channels_required` from `config.py`.

**Behavior:** `lock [channel] [duration min] [reason]` denies @everyone
`send_messages` (defaults to the channel it runs in). Locking records
the previous @everyone overwrite so `unlock` restores exactly that
state; unlock also clears a hand-set lock by resetting the overwrite.
Timed locks live in `lockdown_channels` with a 1-minute auto-unlock
ticker that survives restarts; unlock embeds show `<t:unlock_at:R>`.
`lockall` locks every text channel (already-bot-locked channels keep
their timers; forum channels are skipped — lock those individually).
`slowmode <seconds> [channel] [reason]` caps at 21600 (6h); 0 clears.
`status` lists bot-locked channels with locker, reason, and pending
auto-unlocks.

**Loop note:** the ticker calls `tasks.loop.start()` in `__init__`.
That is safe in pycord (`_get_event_loop` creates/returns the thread
loop the bot then uses); `admin_cog`'s tempban sweep is the pre-existing
precedent. Only `discord.ui.View` construction needed the `on_ready`
move (see tickets above) — do not "fix" loop starts.

## 11. Automod basics

**Files:** `cogs/Automod.py`, table `automod_config`, storage helpers,
`web/blueprints/logger.py` endpoints + Automod card on the Logger
settings page. Registered in `bot.py` COGS and `config.py` tags.

**Commands:** `/automod status|toggle|config` (guild-scoped); the web
toggles share the same `automod_config` row, so both stay in sync.

**Rules (all default OFF):** spam bursts (5 messages in 10s,
configurable), invite links (`discord.gg`/invite, own vanity code
allowed), external links (`http(s)` outside Discord hosts), all-caps
(10+ letters, 80%+ uppercase). **Action:** delete the message + log to
the Logger moderation channel and history. Manage Messages members are
exempt. Log embeds throttle to one per member per rule per 60 seconds
(deletes still happen every time).

**Limits:** no per-channel exemptions, no DM warnings, no escalation,
non-vanity own-server invites still get caught, spam history clears on
restart.

## 12. Auto-threads

**Files:** `cogs/AutoThreads.py`, table `auto_thread_channels`,
storage helpers. Registered in `bot.py` COGS. Fills the `auto_thread`
gap in `config.py` tags.

**Commands:** `/auto_thread` (toggle current channel),
`/set_auto_thread_channel [archive + prefix]`, `/remove`, `/status` —
all guild-scoped, Manage Channels.

**Behavior:** every message in a designated channel gets a discussion
thread named prefix + first 80 characters of the message (author
fallback for empty messages). Skips bots, webhooks, messages already in
threads, replies, and `!` commands, and never tries channels lacking
Create Public Threads permission. Archive choices are 60/1440/4320/10080
minutes; if the server boost level rejects the chosen duration it falls
back to 24h rather than failing.

## 13. Live VC viewer (web)

**Files:** `web/blueprints/voice.py`, `web/templates/voice.html`,
`web/static/js/voice.js`, `web/static/css/voice.css`; `app.py`
registration + route; Live Voice sidebar link on the channels page.

**Behavior:** `GET /api/servers/<guild_id>/voice` (moderator-gated)
reads live voice state from the bot's in-memory cache
(`voice_states` intent, already on — no new table) and the page at
`/servers/<guild_id>/voice` renders it, refreshing every 15 seconds
(pauses while the tab is hidden) with a manual Refresh button. Join
links are `https://discord.com/channels/<guild>/<channel>` (opening one
drops you into the channel; picking a voice channel connects you).

**Limits:** the sidebar link exists only on the Channels page (sidebars
are duplicated per template); no speaking indicator (not reliably in
cache); web-only, no Discord command.

## 14. `/time` command from profile timezones

**Files:** `cogs/TimeCmd.py`. Registered in `bot.py` COGS and
`config.py` tags. No new table — it reads the existing
`profiles.timezone` field.

**Behavior:** guild-scoped `/time [user]` (blank = yourself) formats
the target's current local time with `zoneinfo` (no Discord `<t:>`
markup). No timezone set: self gets a nudge to set one, others get a
"not set" reply, bots get "no profile". **Privacy:** another user's
time shows only when they opted in to `show_local_info` (same rule as
the web bio line); your own time is never gated. That gate is
reversible if the server prefers it open.

## 15. Mod-awardable custom badges

**Files:** `cogs/CustomBadges.py`, tables `custom_badges` +
`custom_badge_awards`, storage helpers, `web/blueprints/profiles.py`
(appends awarded badges to own-stats and public-profile badge lists),
activity-feed lines in `profile.html` / `profile_public.html`.

**Commands:** `/badge create <name> [icon] [description]` (name becomes
a per-server-unique slug; icon defaults to 🏅), `/badge award <badge>
<member>` (badge option autocompletes server badges, name + slug shown),
`/badge remove <badge> <member>`, `/badge delete <badge>` (deletes the
definition + all awards; the reply states the count), `/badge list`
(badges with counts). All guild-scoped, Manage Messages gate. Bots
can't receive badges; re-awarding is rejected.

**Display:** awarded custom badges render in the badge grid alongside
`BADGE_DEFS` on own + public pages (counted in "Badges N"). The API
returns only icon/name/description, never the guild id, so public pages
can't leak server membership. Awards also log to the recipient's
activity feed.

**Limits:** custom badges can't be featured (the edit page only
accepts `BADGE_DEFS` keys); no award expiry; Discord custom-emoji
icons show as raw text on the web shelf.

## 16. Logger export (repair, not a new feature)

**Files:** `cogs/Logger/logger.py` (1,353 → 2,639 bytes),
`cogs/Logger/database.py` (7,851 → 9,630 bytes),
`web/services/event_store.py` (5,199 → 7,201 bytes),
`web/blueprints/logger.py` (10,824 → 11,407 bytes).

**What was broken:** the Logger History page already had an Export CSV
button and endpoint, but it wrote columns that don't exist in the
events table (`event_id`, `user_id`, `channel_id`, `payload` — all
empty), dropped the actual content, and ignored the user/channel/date
filters. The events table only stores `id`, `guild_id`, `category`,
`event_type`, `summary`, `created_at`, and summaries were NULL because
Logger recorded only `embed.description` while embeds carry everything
in fields.

**The fix:** `Logger.send` now records a rich summary (description +
author line + `Field: value` lines, capped at 2000 chars).
`query_events`/`count_events` accept `user_id`, `channel_id`,
`date_from`, `date_to` (epoch; user/channel match summary text, digits
only; LIKE wildcards escaped). `event_store` passes all filters
through; page dates parse as UTC day bounds; rows normalize with ISO
timestamps and `data.description` so the history page shows real times
and descriptions. Export writes `id, guild_id, timestamp` (ISO UTC),
`category, event_type, summary`, with a UTF-8 BOM for Excel and a
`-user-<id>` filename suffix when filtered. Coverage is the Logger
category events table only (message, voice, member, role, channel,
thread, moderation, invite, emoji, sticker, server), capped at 5000
rows (the Logger retention cap). No new tables, no Discord command —
the web Export CSV button was already the trigger and already sends
all filters. Tables were NOT altered to fix this (flattening embed
fields into the summary instead); the fix was verified against a copy
of `message_log.db` before deploying.

**Consequence to know:** old rows (12 at repair time, all NULL
summaries) can never match a user/channel filter — per-user export
only works for events recorded after the restart that picked this up.
Export dates are UTC; Central-day boundaries are a possible follow-up.

## 17. Member directory by interest tags

**Files:** `web/blueprints/directory.py`, `web/templates/directory.html`,
`web/static/css/directory.css`, `web/static/js/directory.js`;
`app.py` registration; Directory nav link in `base.html` (logged-in
users); `list_public_profiles` helper in storage. No new table — tags
already live on profiles (up to 10 per profile).

**Behavior:** `/directory` is login-gated. A tag cloud shows every tag
on public profiles with counts; selecting tags filters by AND (must
have all), and search matches name/bio/status/tags. Results show
public profiles only, under the same privacy rules as public profile
pages: name, avatar, pronouns, bio, status, socials, tags, totals-only
stats, earned badges, DM status, and a link to `/profile/<id>` — no
server list, no per-guild stats, no roles. Timezone/location/country
appear only when `show_local_info` is on.

**Choices:** global directory (not per-server) to match public-profile
visibility; login required but no moderator gate; no friend buttons;
web only. **Open question:** whether the directory should ever be
visible without logging in (public profiles themselves are) — same
question as the feed below.

## 18. Community activity feed page

**Files:** `web/blueprints/feed.py` (`GET /feed` page + `GET /api/feed`,
login-gated like the directory), `web/templates/feed.html`,
`web/static/js/feed.js`, `web/static/css/feed.css`; `app.py`
registration; Feed nav link in `base.html` (next to Directory);
`list_public_activity` helper in storage. No models.py change —
`profile_activity` already exists.

**Behavior:** shows level-ups, daily claims, Eat It or Yeet It rounds,
and badge awards from `profile_activity`, newest first, 30 per page
with a Newer/Older pager and a kind filter (All / Level-ups / Daily
rewards / Game rounds / Badges). Entry wording matches the profile
page exactly. **Privacy:** only users with public profiles appear,
entries link to `/profile/<id>`, and `guild_id` is stripped from API
responses — no server lists or per-guild stats leak.

**Choices:** login-gated like the directory (safer default);
page-based pagination; manual Refresh only (no auto-refresh, to avoid
pagination jumps). **Open question:** same as the directory — public
without login, or keep the gate?
