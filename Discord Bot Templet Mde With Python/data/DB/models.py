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






