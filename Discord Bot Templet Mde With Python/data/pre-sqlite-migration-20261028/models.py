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
