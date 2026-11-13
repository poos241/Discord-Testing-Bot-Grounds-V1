"""Async database access for the bot.

Edition: PostgreSQL (was SQLite).

What this module does:
  * Exposes ``database`` (async, via the ``databases`` library on
    asyncpg) and ``engine`` (sync SQLAlchemy engine on psycopg) — the
    dual shape the rest of the bot already uses. The two URL forms
    are derived from one ``DATABASE_URL``:
      - async: the plain ``postgresql://`` URL (asyncpg).
      - sync:  ``postgresql+psycopg://`` (psycopg 3).
  * Creates the schema on startup: ``metadata.create_all(engine)``
    against the sync engine (SQLAlchemy's DDL for Postgres, generic
    DDL for SQLite, so old rows keep working after a fresh build),
    so deleting a table does not leave the bot broken.
  * Runs self-healing ``ALTER TABLE`` migrations when the bot starts:
    new columns get added in place (Postgres equivalent of the old
    SQLite PRAGMA table_info check: ``information_schema.columns``).

Adding a new table: add the table to ``data/DB/models.py`` and restart
the bot — create_all creates it. Adding a new column: add the column
to ``_PROFILE_COLUMNS`` / ``_GHLOG_COLUMNS`` below, and/or to the
model, and restart — the migration adds it.
"""

import asyncio
import os
import traceback
from urllib.parse import urlparse, urlunparse

import sqlalchemy
from databases import Database
from dotenv import load_dotenv

from data.DB.models import metadata

BASE_DIR = os.path.dirname(os.path.abspath(__file__))  # .../data/DB
DATA_DIR = os.path.dirname(BASE_DIR)  # .../data
BOT_DIR = os.path.dirname(DATA_DIR)  # bot root
os.makedirs(DATA_DIR, exist_ok=True)

# The bot's .env lives at the bot root (CRLF, spaces around ``=`` —
# python-dotenv handles that). Load it here, from the absolute path,
# so this module works no matter which process imports it first (the
# bot's bot.py loads it too, but the website has its own entry point),
# and no matter which folder the process was started from.
load_dotenv(os.path.join(BOT_DIR, ".env"))

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL is not set. Add it to the bot .env, e.g. "
        "DATABASE_URL=postgresql://havenly_bot:<password>@127.0.0.1:5432/havenly"
    )


def _with_scheme(url, scheme):
    """Return ``url`` with its scheme replaced (e.g. ``postgresql``
    -> ``postgresql+psycopg``). Everything else (user, password,
    host, port, database) is untouched."""
    parsed = urlparse(url)
    return urlunparse(parsed._replace(scheme=scheme))


def get_database_url():
    """The async (``databases`` / asyncpg) URL — the plain
    ``postgresql://`` form of DATABASE_URL."""
    return DATABASE_URL


def get_sync_database_url():
    """The sync SQLAlchemy engine URL (psycopg 3 dialect)."""
    return _with_scheme(DATABASE_URL, "postgresql+psycopg")


def get_psycopg_conninfo():
    """A psycopg conninfo string for the synchronous modules
    (``utils/json_sqlite_store.py``, ``cogs/Logger/database.py``) —
    the plain ``postgresql://`` URL works as a conninfo directly."""
    return DATABASE_URL


class SerialisedDatabase(Database):
    """A ``databases.Database`` whose ``connect()`` is safe to call
    concurrently.

    WHY (2026-11-12 cutover rollback): the stock ``Database.connect()``
    is a check-then-act -- ``if self.is_connected: return`` followed
    by ``await self._backend.connect()`` -- with an ``await`` between
    the check and the pool creation. When several cogs call it at the
    same time (every ``before_loop`` does ``if not
    database.is_connected: await database.connect()``), they all pass
    the check and all enter ``PostgresBackend.connect()`` together;
    each creates its own asyncpg pool and the last one wins, orphaning
    the others. Connections are then released into the wrong pool
    (``Pool.release() received invalid connection``) and the backend's
    single-connection slot sticks at "acquired" forever
    (``AssertionError('Connection is already acquired')`` on every
    later ``execute``/``fetch``). On SQLite the pool creation is
    near-instant so the calls never overlapped; on Postgres it takes
    ~1 s, so they always do.

    The fix is one lock around the whole check-and-connect, so exactly
    one caller creates the pool and the rest see ``is_connected`` and
    return. This makes every existing per-cog ``connect()`` call a
    safe no-op once connected -- they are neutralised here, not
    deleted, so a future cog (or a re-enabled one) that calls
    ``connect()`` in its ``before_loop`` is safe too. The single
    intentional connect is in ``bot.py`` ``on_ready``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Created at import time; asyncio.Lock binds to its loop
        # lazily on first use (Python 3.10+), and the bot runs a
        # single event loop, so this is safe.
        self._connect_lock = asyncio.Lock()

    async def connect(self):
        async with self._connect_lock:
            if self.is_connected:
                return
            await super().connect()


database = SerialisedDatabase(get_database_url())
engine = sqlalchemy.create_engine(get_sync_database_url())


# Self-healing schema migrations — starter: if a column did not exist
# at creation, it gets added automatically the next time the bot runs.
# Migration rules, in one place so they survive table recreation.
# These are the LIVE migration dicts (copied verbatim from the live
# db.py, converted to Postgres DDL): only the columns that were added
# to the models after the tables were first created. Every column
# here is already in models.py, so on a fresh schema create_all
# creates them and this migration adds nothing -- it only heals a
# database created before the model gained the column.
_PROFILE_COLUMNS = {
    "show_roles": "BOOLEAN DEFAULT FALSE",
    "roles_guild_id": "VARCHAR DEFAULT ''",
    "roles_position": "VARCHAR DEFAULT 'bottom'",
    "timezone": "VARCHAR DEFAULT ''",
    "location": "VARCHAR DEFAULT ''",
    "country": "VARCHAR DEFAULT ''",
    "show_local_info": "BOOLEAN DEFAULT FALSE",
    "dm_status": "VARCHAR DEFAULT ''",
}

_GHLOG_COLUMNS = {
    "intended_status": "VARCHAR DEFAULT ''",
    "ticket": "VARCHAR DEFAULT ''",
    "approval": "VARCHAR DEFAULT ''",
    "logged_by_id": "VARCHAR DEFAULT ''",
    "invoke_at": "TIMESTAMP",
}


def _existing_columns(_conn, table):
    """Column names present on ``table`` in the current schema.

    Postgres equivalent of the old SQLite ``PRAGMA table_info``.
    """
    rows = _conn.exec_driver_sql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s",
        (table,),
    )
    return {row[0] for row in rows}


def _ensure_profile_columns():
    """Add any missing columns to ``profiles`` in place."""
    with engine.begin() as _conn:
        cols = _existing_columns(_conn, "profiles")
        for col_name, ddl in _PROFILE_COLUMNS.items():
            if col_name not in cols:
                _conn.exec_driver_sql(
                    "ALTER TABLE profiles ADD COLUMN %s %s" % (col_name, ddl)
                )
                print("[DB] Profile migration: added column %s" % col_name)


def _ensure_ghlog_columns():
    """Add any missing columns to ``ghlog_items`` in place."""
    with engine.begin() as _conn:
        cols = _existing_columns(_conn, "ghlog_items")
        for col_name, ddl in _GHLOG_COLUMNS.items():
            if col_name not in cols:
                _conn.exec_driver_sql(
                    "ALTER TABLE ghlog_items ADD COLUMN %s %s"
                    % (col_name, ddl)
                )
                print("[DB] GHLog migration: added column %s" % col_name)


def setup_database():
    """Create tables + run the self-healing column migrations.

    Importing this module does NOT run it — the FIRST bot that opens
    runs it (or first website that loads it), so the tables and
    columns are created exactly once per process start.
    """
    try:
        print("[DB] Creating tables if they do not exist...")
        metadata.create_all(engine)
        print("[DB] Tables ready.")
        _ensure_profile_columns()
        _ensure_ghlog_columns()
    except Exception:
        print("[DB] Failed to initialize database:")
        traceback.print_exc()


DB_INITIALIZED = False


def ensure_db_initialized():
    """Run setup_database() once per process."""
    global DB_INITIALIZED
    if not DB_INITIALIZED:
        setup_database()
        DB_INITIALIZED = True
