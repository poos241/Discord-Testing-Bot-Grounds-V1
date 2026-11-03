# db.py
import os
import traceback

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

# Split-required boot hardening (BRIDGE_CONTRACT.md section 8): this
# runs at import in BOTH processes. A locked/corrupt DB at website
# startup used to kill the import; now it logs loudly and records a
# health flag instead, so the website still boots (degraded). Same
# pattern as _ensure_profile_columns below.
DB_CREATE_ERROR = None
try:
    metadata.create_all(engine)
except Exception as _exc:
    DB_CREATE_ERROR = repr(_exc)
    print("[DB] ERROR: metadata.create_all FAILED; the database may be "
          "locked or corrupt. The website will keep booting degraded, "
          "but DB-backed pages will fail until this is fixed.")
    print(f"[DB] create_all error: {_exc!r}")
    traceback.print_exc()

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

# Set to repr(exc) when the boot-time profile-column migration
# fails, else None. Surfaced by /api/debug/bot-status so a broken
# migration is visible in the debug panel instead of looking like a
# clean boot and failing later on profile saves with a confusing
# runtime error. The bot stays up (a profiles-table problem must not
# take moderation, tickets, and everything else down with it), but
# the failure is logged loudly below.
PROFILE_MIGRATION_ERROR = None


def _ensure_profile_columns(_engine):
    """Add any missing profile columns so old databases heal on boot."""
    global PROFILE_MIGRATION_ERROR
    PROFILE_MIGRATION_ERROR = None
    try:
        with _engine.begin() as _conn:
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
        PROFILE_MIGRATION_ERROR = repr(_exc)
        print("[DB] ERROR: profile column migration FAILED; the profiles "
              "table is stale and profile saves will fail. See "
              "/api/debug/bot-status (profile_migration_error).")
        print(f"[DB] Migration error: {_exc!r}")
        traceback.print_exc()


_ensure_profile_columns(engine)
