from data.DB.db import database
from data.DB.models import welcome_data, main_vc_map, xp_timestamps, threads_settings, levels, ticket_config, active_tickets, ticket_records
from datetime import datetime

async def get_welcome(guild_id: str):
    row = await database.fetch_one(welcome_data.select().where(welcome_data.c.guild_id == guild_id))
    return dict(row) if row else {}

async def save_welcome(guild_id: str, payload: dict):
    await database.execute(
        welcome_data.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_mainvc(guild_id: str):
    row = await database.fetch_one(main_vc_map.select().where(main_vc_map.c.guild_id == guild_id))
    return dict(row) if row else {}

async def save_mainvc(guild_id: str, payload: dict):
    await database.execute(
        main_vc_map.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_xp(guild_id: str):
    row = await database.fetch_one(xp_timestamps.select().where(xp_timestamps.c.guild_id == guild_id))
    return row["data"] if row else {}

async def save_xp(guild_id: str, data: dict):
    await database.execute(
        xp_timestamps.insert()
        .values(guild_id=guild_id, data=data)
        .prefix_with("OR REPLACE")
    )

async def get_threads_settings(guild_id: str):
    """
    Fetches the thread settings for a specific guild.
    Ensures correct column usage and avoids SQL injection/misinterpretation.
    """
    # Cast to string just to be safe — even if already str
    guild_id_str = str(guild_id)

    # Construct safe query
    query = threads_settings.select().where(threads_settings.c.guild_id == guild_id_str)

    # Fetch one row
    row = await database.fetch_one(query)
    return row

async def save_threads_settings(guild_id: str, payload: dict):
    await database.execute(
        threads_settings.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_levels(guild_id: str):
    row = await database.fetch_one(levels.select().where(levels.c.guild_id == guild_id))
    return row["data"] if row else {}

async def save_levels(guild_id: str, data: dict):
    from discord.utils import get  # just in case you use it
    guild_name = data.get("settings", {}).get("guild_name", "Unknown")
    query = levels.insert().values(
        guild_id=guild_id,
        guild_name=guild_name,
        data=data
    ).prefix_with("OR REPLACE")
    await database.execute(query)
    
    
    
    
    
    
async def get_ticket_config(gid: str):
    row = await database.fetch_one(ticket_config.select().where(ticket_config.c.guild_id == str(gid)))
    return row["config"] if row else {}

async def save_ticket_config(gid: str, config: dict):
    await database.execute(
        ticket_config.insert().values(
            guild_id=str(gid),
            guild_name=config.get("guild_name", ""),
            config=config
        ).prefix_with("OR REPLACE")
    )

async def get_active_tickets(gid: str):
    row = await database.fetch_one(active_tickets.select().where(active_tickets.c.guild_id == str(gid)))
    return row["active"] if row else {}

async def save_active_tickets(gid: str, active: dict):
    await database.execute(
        active_tickets.insert().values(
            guild_id=str(gid),
            guild_name=active.get("guild_name", ""),
            active=active
        ).prefix_with("OR REPLACE")
    )

async def get_ticket_records(gid: str):
    row = await database.fetch_one(ticket_records.select().where(ticket_records.c.guild_id == str(gid)))
    return row["records"] if row else {}

async def save_ticket_records(gid: str, records: dict):
    await database.execute(
        ticket_records.insert().values(
            guild_id=str(gid),
            records=records
        ).prefix_with("OR REPLACE")
    )
    
    
    
    
    # inside storage.py
import json, os, aiosqlite

async def get_auto_thread_config(guild_id):
    async with aiosqlite.connect("botdata.db") as db:
        async with db.execute("SELECT config FROM threads_config WHERE guild_id = ?", (str(guild_id),)) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else {}

async def save_auto_thread_config(guild_id, config):
    config_json = json.dumps(config)
    async with aiosqlite.connect("botdata.db") as db:
        await db.execute("REPLACE INTO threads_config (guild_id, config) VALUES (?, ?)", (str(guild_id), config_json))
        await db.commit()

async def get_active_threads(guild_id):
    async with aiosqlite.connect("botdata.db") as db:
        async with db.execute("SELECT active FROM threads_active WHERE guild_id = ?", (str(guild_id),)) as cursor:
            row = await cursor.fetchone()
            return json.loads(row[0]) if row else {}

async def save_active_threads(guild_id, active_data):
    active_json = json.dumps(active_data)
    async with aiosqlite.connect("botdata.db") as db:
        await db.execute("REPLACE INTO threads_active (guild_id, active) VALUES (?, ?)", (str(guild_id), active_json))
        await db.commit()
