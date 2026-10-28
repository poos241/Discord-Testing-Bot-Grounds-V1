import sqlalchemy
from datetime import datetime
from sqlalchemy.sql import func

metadata = sqlalchemy.MetaData()

def timestamp_column():
    return sqlalchemy.Column("updated_at", sqlalchemy.DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

# Table definitions based on your JSON files

welcome_data = sqlalchemy.Table(
    "welcome_data", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("guild_name", sqlalchemy.String),
    sqlalchemy.Column("welcome_channel_id", sqlalchemy.String),
    sqlalchemy.Column("welcome_image_url", sqlalchemy.String),
    sqlalchemy.Column("welcome_embed_title", sqlalchemy.String),
    sqlalchemy.Column("welcome_message", sqlalchemy.String),
    sqlalchemy.Column("auto_role_id", sqlalchemy.String),
    sqlalchemy.Column("auto_role_name", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, nullable=False, server_default=func.now()),
    timestamp_column()
)

main_vc_map = sqlalchemy.Table(
    "main_vc_map", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("guild_name", sqlalchemy.String),
    sqlalchemy.Column("main_vc_id", sqlalchemy.String),
    sqlalchemy.Column("main_category_id", sqlalchemy.String),
    sqlalchemy.Column("message_channel", sqlalchemy.String),
    sqlalchemy.Column("dm_users", sqlalchemy.Boolean),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, nullable=False, server_default=func.now()),
    timestamp_column()
)

xp_timestamps = sqlalchemy.Table(
    "xp_timestamps", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, nullable=False, server_default=func.now()),
    timestamp_column()
)



threads_settings = sqlalchemy.Table(
    "threads_settings",
    metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("config", sqlalchemy.JSON),
    ##sqlalchemy.Column("thread_name_format", sqlalchemy.String),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, nullable=False, server_default=func.now()),
    timestamp_column()
    # Add other settings columns here
)


levels = sqlalchemy.Table(
    "levels", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("guild_name", sqlalchemy.String),  # ✅ new
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)






ticket_config = sqlalchemy.Table(
    "ticket_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("guild_name", sqlalchemy.String),
    sqlalchemy.Column("config", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

active_tickets = sqlalchemy.Table(
    "active_tickets", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("guild_name", sqlalchemy.String),
    sqlalchemy.Column("active", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

ticket_records = sqlalchemy.Table(
    "ticket_records", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("records", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)








# Web dashboard user profiles (migrated from data/profiles.json).
# Scalar fields are real columns so they can be queried directly;
# socials/tags stay JSON because their shape is free-form.

profiles = sqlalchemy.Table(
    "profiles", metadata,
    sqlalchemy.Column("user_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("bio", sqlalchemy.String, default=""),
    sqlalchemy.Column("accent", sqlalchemy.String, default="#5865F2"),
    sqlalchemy.Column("banner", sqlalchemy.String, default=""),
    sqlalchemy.Column("status", sqlalchemy.String, default=""),
    sqlalchemy.Column("avatar_url", sqlalchemy.String, default=""),
    sqlalchemy.Column("background_url", sqlalchemy.String, default=""),
    sqlalchemy.Column("pronouns", sqlalchemy.String, default=""),
    sqlalchemy.Column("display_name", sqlalchemy.String, default=""),
    sqlalchemy.Column("featured_badge", sqlalchemy.String, default=""),
    sqlalchemy.Column("featured_stat", sqlalchemy.String, default=""),
    sqlalchemy.Column("public", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("show_roles", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("roles_guild_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("roles_position", sqlalchemy.String, default="bottom"),
    sqlalchemy.Column("timezone", sqlalchemy.String, default=""),
    sqlalchemy.Column("location", sqlalchemy.String, default=""),
    sqlalchemy.Column("country", sqlalchemy.String, default=""),
    sqlalchemy.Column("show_local_info", sqlalchemy.Boolean, default=False),
    sqlalchemy.Column("dm_status", sqlalchemy.String, default=""),
    sqlalchemy.Column("socials", sqlalchemy.JSON, default={}),
    sqlalchemy.Column("tags", sqlalchemy.JSON, default=[]),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)


# Per-user activity feed for profiles. `ts` is a unix epoch (UTC) so
# the frontend can render it in the viewer's timezone. `detail` is
# free-form per kind: level_up {level}, daily_claim {streak},
# game_round {food, verdict, voted, majority, points}.

profile_activity = sqlalchemy.Table(
    "profile_activity", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("user_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("kind", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("detail", sqlalchemy.JSON, default={}),
    sqlalchemy.Column("ts", sqlalchemy.Integer, nullable=False)
)


# Question of the Day (QOTD) tables. Questions live in one global pool;
# per-guild state (config, history, exclusions) is keyed by guild_id.
# New tables only — create_all() creates these on the next bot boot.

qotd_questions = sqlalchemy.Table(
    "qotd_questions", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("text", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False, default="approved"),
    sqlalchemy.Column("active", sqlalchemy.Boolean, nullable=False, default=True),
    sqlalchemy.Column("source", sqlalchemy.String, nullable=False, default="seed"),
    sqlalchemy.Column("submitter_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("submitted_guild_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now())
)

qotd_config = sqlalchemy.Table(
    "qotd_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("channel_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("post_time", sqlalchemy.String, nullable=False, default="09:00"),
    sqlalchemy.Column("timezone", sqlalchemy.String, nullable=False, default="America/Chicago"),
    sqlalchemy.Column("enabled", sqlalchemy.Boolean, nullable=False, default=True)
)

qotd_history = sqlalchemy.Table(
    "qotd_history", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("question_id", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("posted_date", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("message_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("thread_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("skipped", sqlalchemy.Boolean, nullable=False, default=False)
)

qotd_guild_exclusions = sqlalchemy.Table(
    "qotd_guild_exclusions", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("question_id", sqlalchemy.Integer, primary_key=True)
)


# Support ticket system (built new 2026-10-27). Deliberately separate
# from the legacy ticket_config / active_tickets / ticket_records
# tables above, which belong to an earlier ticket attempt and are
# left untouched here. One row per ticket; per-guild settings live
# in ticket_guild_config. New tables only — create_all() creates
# these on the next bot boot.

ticket_guild_config = sqlalchemy.Table(
    "ticket_guild_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("staff_role_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("category_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("log_channel_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("panel_channel_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("panel_message_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("next_number", sqlalchemy.Integer, nullable=False, default=1),
    sqlalchemy.Column("enabled", sqlalchemy.Boolean, nullable=False, default=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

support_tickets = sqlalchemy.Table(
    "support_tickets", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("number", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("user_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("channel_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False, default="open"),
    sqlalchemy.Column("topic", sqlalchemy.String, default=""),
    sqlalchemy.Column("claimed_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("closed_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("close_reason", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("closed_at", sqlalchemy.DateTime)
)


# Ban/timeout appeals + mod notes search (built 2026-10-27). Appeals
# live here, NOT in mod_data.json: they need listing, review state,
# and per-guild config, which the JSON user-record shape doesn't fit.
# The mod notes/warns/cases being searched still live in
# mod_data.json (written by the mod panel) — search reads that file,
# it does not move it. New tables only — create_all() creates these
# on the next bot boot.

appeal_guild_config = sqlalchemy.Table(
    "appeal_guild_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("appeals_channel_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("staff_role_id", sqlalchemy.String, default=""),
    sqlalchemy.Column("enabled", sqlalchemy.Boolean, nullable=False, default=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

appeals = sqlalchemy.Table(
    "appeals", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("user_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("user_name", sqlalchemy.String, default=""),
    sqlalchemy.Column("appeal_type", sqlalchemy.String, nullable=False, default="ban"),
    sqlalchemy.Column("text", sqlalchemy.String, nullable=False, default=""),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False, default="pending"),
    sqlalchemy.Column("decided_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("decision_reason", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("decided_at", sqlalchemy.DateTime)
)

# JSON -> SQLite migration (built 2026-10-28). The remaining JSON
# stores moved here from data/*.json, following the profiles
# migration pattern and the levels JSON-blob precedent: one row per
# top-level key (guild_id, or channel_id for the per-channel
# eatyeet files), with the old file's subtree as JSON in `data`.
# The sync accessor is utils/json_sqlite_store.py (all callers are
# synchronous, so the async storage helpers are not used here).
# New tables only -- create_all() creates these on the next bot boot
# and never alters an existing table. The json_migrations table
# records each store's one-time import so the legacy JSON file is
# never re-imported after migration; the original JSON files stay
# on disk untouched as the rollback copy.

mod_data = sqlalchemy.Table(
    "mod_data", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

watchlist_data = sqlalchemy.Table(
    "watchlist_data", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

eatyeet_stats = sqlalchemy.Table(
    "eatyeet_stats", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

eatyeet_suggestions = sqlalchemy.Table(
    "eatyeet_suggestions", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

eatyeet_active = sqlalchemy.Table(
    "eatyeet_active", metadata,
    sqlalchemy.Column("channel_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

eatyeet_rematch = sqlalchemy.Table(
    "eatyeet_rematch", metadata,
    sqlalchemy.Column("channel_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

json_migrations = sqlalchemy.Table(
    "json_migrations", metadata,
    sqlalchemy.Column("store", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("source_sha256", sqlalchemy.String, default=""),
    sqlalchemy.Column("keys", sqlalchemy.Integer, default=0),
    sqlalchemy.Column("migrated_at", sqlalchemy.DateTime, server_default=func.now())
)

# Website friend system (built 2026-10-28). Mutual friendships only:
# one row per pair of users (requester/addressee record who started
# the current request). status is pending / accepted / declined. A
# declined row is kept and flipped back to pending if a new request
# is sent, so there is never more than one row per pair. Unfriend
# and cancel delete the row outright. created_ts / decided_ts are
# unix epochs (same convention as profile_activity.ts) so the
# notification bell can sort friend requests without parsing
# datetimes. friend_settings holds the "do not send me friend
# requests" opt-out (default allow); it is a separate table, not a
# profiles column, so create_all() creates it on the next bot boot
# with no ALTER TABLE migration for the existing profiles table.
# New tables only -- create_all() creates these on the next bot boot
# and never alters an existing table.

friendships = sqlalchemy.Table(
    "friendships", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("requester_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("addressee_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("status", sqlalchemy.String, nullable=False, default="pending"),
    sqlalchemy.Column("requester_name", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_ts", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("decided_ts", sqlalchemy.Integer)
)

friend_settings = sqlalchemy.Table(
    "friend_settings", metadata,
    sqlalchemy.Column("user_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("allow_requests", sqlalchemy.Boolean, nullable=False, default=True)
)

# Voice time XP + VC leaderboard (built 2026-10-28; see cogs/VoiceXP.py).
# Per-guild settings plus one row per member per guild: opt-in flag,
# banked totals, and today's XP toward the daily cap (xp_day is a
# UTC YYYY-MM-DD string; a row whose xp_day is not today counts as
# 0 toward today's cap). Unbanked sub-5-minute minutes live only in
# the cog's memory, never here. New tables only -- create_all()
# creates these on the next bot boot and never alters an existing
# table.

voice_xp_config = sqlalchemy.Table(
    "voice_xp_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("xp_per_minute", sqlalchemy.Integer, nullable=False, default=1),
    sqlalchemy.Column("daily_cap_xp", sqlalchemy.Integer, nullable=False, default=100),
    sqlalchemy.Column("enabled", sqlalchemy.Boolean, nullable=False, default=True),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

voice_xp_users = sqlalchemy.Table(
    "voice_xp_users", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("user_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("opted_in", sqlalchemy.Boolean, nullable=False, default=False),
    sqlalchemy.Column("display_name", sqlalchemy.String, default=""),
    sqlalchemy.Column("total_minutes", sqlalchemy.Integer, nullable=False, default=0),
    sqlalchemy.Column("total_voice_xp", sqlalchemy.Integer, nullable=False, default=0),
    sqlalchemy.Column("xp_today", sqlalchemy.Integer, nullable=False, default=0),
    sqlalchemy.Column("xp_day", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now()),
    sqlalchemy.PrimaryKeyConstraint("guild_id", "user_id")
)

# Lockdown + slowmode (built 2026-10-28; see cogs/Lockdown.py).
# One row per channel the bot has locked. previous_send_messages
# records what @everyone send_messages was before the lock
# (1 = allowed, 0 = denied, -1 = unset) so unlocking restores
# exactly that state. unlock_at is epoch seconds, or NULL for a
# manual lock that only a mod clears; the 1-minute ticker in the
# cog auto-unlocks due rows, and rows survive a bot restart.
# New table only -- create_all() creates it on the next bot boot
# and never alters an existing table.

lockdown_channels = sqlalchemy.Table(
    "lockdown_channels", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("channel_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("previous_send_messages", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("locked_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("locked_at", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("unlock_at", sqlalchemy.Integer),
    sqlalchemy.Column("reason", sqlalchemy.String, default=""),
    sqlalchemy.Column("scope", sqlalchemy.String, default="channel"),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now()),
    sqlalchemy.PrimaryKeyConstraint("guild_id", "channel_id")
)

# Automod basics (built 2026-10-28; see cogs/Automod.py). One row per
# guild; every rule defaults to OFF, so a server that never touches
# /automod or the web Logger settings page gets no filtering at all.
# spam_threshold / spam_window_seconds are the only numeric settings
# (caps uses fixed 10-letter / 80%-uppercase thresholds in the cog).
# New table only -- create_all() creates it on the next bot boot
# and never alters an existing table.

automod_config = sqlalchemy.Table(
    "automod_config", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("spam_enabled", sqlalchemy.Boolean, nullable=False, default=False),
    sqlalchemy.Column("invites_enabled", sqlalchemy.Boolean, nullable=False, default=False),
    sqlalchemy.Column("external_links_enabled", sqlalchemy.Boolean, nullable=False, default=False),
    sqlalchemy.Column("caps_enabled", sqlalchemy.Boolean, nullable=False, default=False),
    sqlalchemy.Column("spam_threshold", sqlalchemy.Integer, nullable=False, default=5),
    sqlalchemy.Column("spam_window_seconds", sqlalchemy.Integer, nullable=False, default=10),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now())
)

# Auto-threads (built 2026-10-28; see cogs/AutoThreads.py). One row
# per designated channel: which text channels get an automatic
# discussion thread per message, how long until the thread
# auto-archives (Discord allows 60 / 1440 / 4320 / 10080 minutes),
# and an optional prefix put in front of every thread name in that
# channel. Deliberately separate from the legacy threads_settings
# table above (a per-guild JSON blob no code ever read). New table
# only -- create_all() creates it on the next bot boot and never
# alters an existing table.

auto_thread_channels = sqlalchemy.Table(
    "auto_thread_channels", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("channel_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("archive_minutes", sqlalchemy.Integer, nullable=False, default=1440),
    sqlalchemy.Column("name_prefix", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.Column("updated_at", sqlalchemy.DateTime, server_default=func.now(), onupdate=func.now()),
    sqlalchemy.PrimaryKeyConstraint("guild_id", "channel_id")
)


# Mod-awardable custom badges (built 2026-10-28; see cogs/CustomBadges.py).
# Mods create badge definitions per guild and award them to members;
# awarded badges show on the profile badge shelf next to the hard-coded
# BADGE_DEFS badges (see web/blueprints/profiles.py get_custom_badges).
# New tables only -- create_all() creates them on the next bot boot
# and never alters an existing table. Slugs are unique per guild so
# a badge is always addressable by (guild, slug); awards are unique
# per (badge, member) so a member cannot receive the same badge twice.

custom_badges = sqlalchemy.Table(
    "custom_badges", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("slug", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("name", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("icon", sqlalchemy.String, default=""),
    sqlalchemy.Column("description", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("created_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.UniqueConstraint("guild_id", "slug")
)

custom_badge_awards = sqlalchemy.Table(
    "custom_badge_awards", metadata,
    sqlalchemy.Column("id", sqlalchemy.Integer, primary_key=True, autoincrement=True),
    sqlalchemy.Column("badge_id", sqlalchemy.Integer, nullable=False),
    sqlalchemy.Column("guild_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("user_id", sqlalchemy.String, nullable=False),
    sqlalchemy.Column("awarded_by", sqlalchemy.String, default=""),
    sqlalchemy.Column("awarded_at", sqlalchemy.DateTime, server_default=func.now()),
    sqlalchemy.UniqueConstraint("badge_id", "user_id")
)
