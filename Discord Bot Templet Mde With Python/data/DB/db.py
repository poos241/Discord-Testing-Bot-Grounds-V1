# db.py
import os
import sqlalchemy
from databases import Database
from data.DB.models import metadata

# Resolve the data dir relative to this file so the bot works
# no matter which folder you launch it from.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../data/DB
DATA_DIR = os.path.dirname(os.path.dirname(BASE_DIR))  # .../data
os.makedirs(DATA_DIR, exist_ok=True)

DATABASE_URL = f"sqlite:///{os.path.join(DATA_DIR, 'bot.db')}"

database = Database(DATABASE_URL)
engine = sqlalchemy.create_engine(DATABASE_URL)
metadata.create_all(engine)

# create_all() never adds columns to a table that already exists, so
# when a new profile field ships, an existing bot.db would reject
# saves with "Unconsumed column names". Add any missing columns here
# so old databases heal themselves on the next bot boot.
_PROFILE_COLUMNS = {
    "show_roles": "BOOLEAN DEFAULT 0",
    "roles_guild_id": "VARCHAR DEFAULT ''",
    "roles_position": "VARCHAR DEFAULT 'bottom'",
    "timezone": "VARCHAR DEFAULT ''",
    "location": "VARCHAR DEFAULT ''",
    "country": "VARCHAR DEFAULT ''",
    "show_local_info": "BOOLEAN DEFAULT 0",
    "dm_status": "VARCHAR DEFAULT ''",
}

try:
    with engine.begin() as _conn:
        _existing = {
            row[1]
            for row in _conn.exec_driver_sql("PRAGMA table_info(profiles)")
        }
        for _name, _ddl in _PROFILE_COLUMNS.items():
            if _name not in _existing:
                _conn.exec_driver_sql(
                    f"ALTER TABLE profiles ADD COLUMN {_name} {_ddl}"
                )
                print(f"[DB] Added missing column profiles.{_name}")
except Exception as _exc:
    print(f"[DB] Profile column migration skipped: {_exc}")
