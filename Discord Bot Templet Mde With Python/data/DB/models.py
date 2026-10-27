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
