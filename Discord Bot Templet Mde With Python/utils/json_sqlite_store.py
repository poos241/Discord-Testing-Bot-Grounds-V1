# utils/json_sqlite_store.py
#
# Sync SQLite backing store for the bot's remaining JSON data files.
#
# Why this module exists: mod_data, watchlist, and the eatyeet_* files
# were the last JSON stores left after profiles moved to SQLite. Every
# reader/writer of those files goes through config.load_json/save_json,
# which are synchronous (cog __init__, Flask routes, background sweeps),
# so the async `databases` helpers in data/DB/Storage/storage.py cannot
# be used here without rewriting dozens of call sites. This module keeps
# the exact same dict API (load -> dict, save(dict)) but stores the data
# in the bot's SQLite database (bot.db) using only the standard library.
#
# Schema: one row per top-level key, in tables declared in
# data/DB/models.py (the canonical schema; the CREATE TABLE IF NOT
# EXISTS statements here mirror it so the store also works before
# data/DB/db.py's create_all() runs, and they never alter an existing
# table). Values are JSON text in a `data` column, the same shape the
# old files held -- the same JSON-blob pattern the `levels` table
# already uses.
#
#   mod_data.json            -> mod_data            (key: guild_id)
#   watchlist_data.json      -> watchlist_data      (key: guild_id)
#   eatyeet_stats.json       -> eatyeet_stats       (key: guild_id)
#   eatyeet_suggestions.json -> eatyeet_suggestions  (key: guild_id)
#   eatyeet_active.json      -> eatyeet_active      (key: channel_id)
#   eatyeet_rematch.json     -> eatyeet_rematch     (key: channel_id)
#
# Migration (lazy, one-time, like profiles): the first load or save of
# a store checks the json_migrations table. If no migration row exists
# and the legacy data/<file> exists, it is copied to
# data/<file>.sqlite-backup FIRST, then imported row by row, then the
# migration row is recorded -- all in one transaction, so a crash
# mid-import leaves no half-imported state. The original JSON file is
# NEVER deleted or overwritten by this module; it stays on disk as the
# rollback copy. After migration, the JSON file is only ever read again
# when the store was NEVER migrated (fresh database, migration row
# absent). Once migrated, a persistent SQLite read failure raises
# instead of returning the frozen pre-migration file: returning it
# would let the next save overwrite the live table with stale data.
#
# Rollback: restore the pre-migration copies of config.py (and the
# other edited .py files) and the bot will read the JSON files again.
# The JSON files still hold their pre-migration contents, so nothing
# written before the migration is lost -- but note that anything
# written to SQLite AFTER migration is not in the JSON files, so a
# rollback discards post-migration changes. That is the same trade-off
# the profiles migration had.
#
# Concurrency: every call opens its own short-lived sqlite3 connection
# (never shared across threads -- the bot thread and the Flask web
# thread both use this module). Saves use BEGIN IMMEDIATE and retry a
# few times on a locked database before giving up.

import hashlib
import json
import os
import sqlite3
import time

_BASE = os.path.dirname(os.path.abspath(__file__))  # utils/
BOT_ROOT = os.path.dirname(_BASE)
DATA_DIR = os.path.join(BOT_ROOT, "data")

# filename -> (table, key column)
STORES = {
    "mod_data.json": ("mod_data", "guild_id"),
    "watchlist_data.json": ("watchlist_data", "guild_id"),
    "eatyeet_stats.json": ("eatyeet_stats", "guild_id"),
    "eatyeet_suggestions.json": ("eatyeet_suggestions", "guild_id"),
    "eatyeet_active.json": ("eatyeet_active", "channel_id"),
    "eatyeet_rematch.json": ("eatyeet_rematch", "channel_id"),
}

_MIGRATIONS_TABLE = "json_migrations"

# Mirrors data/DB/models.py (canonical schema). CREATE TABLE IF NOT
# EXISTS never touches an existing table.
_TABLE_DDL = {
    "mod_data": (
        "CREATE TABLE IF NOT EXISTS mod_data ("
        "guild_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    "watchlist_data": (
        "CREATE TABLE IF NOT EXISTS watchlist_data ("
        "guild_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    "eatyeet_stats": (
        "CREATE TABLE IF NOT EXISTS eatyeet_stats ("
        "guild_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    "eatyeet_suggestions": (
        "CREATE TABLE IF NOT EXISTS eatyeet_suggestions ("
        "guild_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    "eatyeet_active": (
        "CREATE TABLE IF NOT EXISTS eatyeet_active ("
        "channel_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    "eatyeet_rematch": (
        "CREATE TABLE IF NOT EXISTS eatyeet_rematch ("
        "channel_id VARCHAR PRIMARY KEY, data JSON, "
        "created_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "updated_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
    ),
    _MIGRATIONS_TABLE: (
        "CREATE TABLE IF NOT EXISTS json_migrations ("
        "store VARCHAR PRIMARY KEY, "
        "migrated_at DATETIME DEFAULT CURRENT_TIMESTAMP, "
        "source_sha256 VARCHAR DEFAULT '', keys INTEGER DEFAULT 0)"
    ),
}

_SAVE_RETRIES = 5


def _db_path():
    """bot.db lives at the bot root (see data/DB/db.py); fall back to
    data/bot.db if that is the layout on this machine."""
    primary = os.path.join(BOT_ROOT, "bot.db")
    if os.path.exists(primary):
        return primary
    alt = os.path.join(DATA_DIR, "bot.db")
    if os.path.exists(alt):
        return alt
    return primary


def legacy_path(filename):
    return os.path.join(DATA_DIR, filename)


def backup_path(filename):
    return os.path.join(DATA_DIR, filename + ".sqlite-backup")


def _ensure_tables(conn):
    for ddl in _TABLE_DDL.values():
        conn.execute(ddl)


def _migrate(conn, filename):
    """One-time import for one store. Must be called inside a write
    transaction; it commits nothing itself. Returns True when the
    store is migrated (or was already), False when the legacy file
    exists but could not be parsed (migration is retried next time)."""
    row = conn.execute(
        "SELECT store FROM json_migrations WHERE store = ?", (filename,)
    ).fetchone()
    if row is not None:
        return True
    table, _key_col = STORES[filename]
    legacy = legacy_path(filename)
    if not os.path.exists(legacy):
        conn.execute(
            "INSERT INTO json_migrations (store, source_sha256, keys)"
            " VALUES (?, '', 0)",
            (filename,),
        )
        return True
    with open(legacy, "rb") as f:
        raw = f.read()
    if not raw.strip():
        # Empty file meant "no data" under the old loader too.
        parsed = {}
    else:
        try:
            parsed = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            print(
                "[JSON-SQLite] WARNING: legacy %s is not valid JSON; "
                "leaving it unmigrated (SQLite store starts empty)."
                % filename
            )
            return False
    if not isinstance(parsed, dict):
        print(
            "[JSON-SQLite] WARNING: legacy %s is not a JSON object; "
            "leaving it unmigrated." % filename
        )
        return False
    backup = backup_path(filename)
    if not os.path.exists(backup):
        # Backup BEFORE importing; never overwrite an earlier backup.
        with open(backup, "wb") as f:
            f.write(raw)
    for key, value in parsed.items():
        conn.execute(
            "INSERT OR REPLACE INTO %s (%s, data) VALUES (?, ?)"
            % (table, STORES[filename][1]),
            (str(key), json.dumps(value)),
        )
    conn.execute(
        "INSERT INTO json_migrations (store, source_sha256, keys)"
        " VALUES (?, ?, ?)",
        (filename, hashlib.sha256(raw).hexdigest(), len(parsed)),
    )
    print(
        "[JSON-SQLite] Migrated %s -> %s (%d keys; backup kept at %s)"
        % (filename, table, len(parsed), backup)
    )
    return True


def _read_legacy_file(filename):
    """Best-effort read of the legacy JSON file (fallback only)."""
    try:
        with open(legacy_path(filename), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _was_migrated(filename):
    """True when a json_migrations row exists for this store, False
    when the database is readable and has no such row, None when the
    check itself cannot run (database unreadable). A None answer must
    be treated as "unknown, do not trust the legacy file"."""
    try:
        conn = sqlite3.connect(
            "file:%s?mode=ro" % _db_path(), uri=True, timeout=10
        )
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if _MIGRATIONS_TABLE not in tables:
                return False
            return (
                conn.execute(
                    "SELECT store FROM json_migrations WHERE store = ?",
                    (filename,),
                ).fetchone()
                is not None
            )
        finally:
            conn.close()
    except Exception:
        return None


def _rows_to_dict(rows, table):
    """Parse SELECT (key, data) rows into a dict, skipping unreadable rows."""
    out = {}
    for key, raw in rows:
        try:
            out[key] = json.loads(raw)
        except (ValueError, TypeError):
            print(
                "[JSON-SQLite] WARNING: skipping unreadable row %r in %s"
                % (key, table)
            )
    return out


def _load_store_readonly(filename, table, key_col):
    """Read a migrated store on a read-only connection.

    Returns the rows when the store's table exists and its migration
    row is present, else None (caller falls through to the write
    path, which creates/migrates). Raises on any other failure so the
    caller can fall through too -- the write path owns the retries
    and the legacy-fallback decision.
    """
    conn = sqlite3.connect(
        "file:%s?mode=ro" % _db_path(), uri=True, timeout=10
    )
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        if table not in tables or _MIGRATIONS_TABLE not in tables:
            return None
        row = conn.execute(
            "SELECT store FROM json_migrations WHERE store = ?",
            (filename,),
        ).fetchone()
        if row is None:
            return None
        return conn.execute(
            "SELECT %s, data FROM %s ORDER BY %s" % (key_col, table, key_col)
        ).fetchall()
    finally:
        conn.close()


def load_store(filename):
    """Return the store's contents as a dict, exactly like the old
    config.load_json() did ({} when empty/missing).

    Transient locked-database errors are retried like save_store does.
    On a persistent failure the legacy file is returned ONLY when the
    store was never migrated; once migrated (or when migration status
    cannot be established) this raises instead of returning the frozen
    pre-migration file, because the next save would overwrite the live
    table with that stale data.
    """
    if filename not in STORES:
        raise ValueError("No SQLite store for %r" % filename)
    table, key_col = STORES[filename]
    # Fast path: when the schema is ready and this store is migrated,
    # read without taking a write lock, so a load can never stall
    # behind (or block) a writer. Before this, every load did
    # BEGIN IMMEDIATE + commit on the event loop, and the board loop's
    # 1-minute tick stalled the Discord heartbeat for 10-20s while
    # the web thread held the lock.
    try:
        rows = _load_store_readonly(filename, table, key_col)
        if rows is not None:
            return _rows_to_dict(rows, table)
    except Exception:
        pass  # fall through to the write path below
    rows = None
    last_exc = None
    for attempt in range(_SAVE_RETRIES):
        try:
            conn = sqlite3.connect(_db_path(), timeout=30)
            try:
                conn.execute("BEGIN IMMEDIATE")
                _ensure_tables(conn)
                _migrate(conn, filename)
                conn.commit()
                rows = conn.execute(
                    "SELECT %s, data FROM %s ORDER BY %s" % (key_col, table, key_col)
                ).fetchall()
            finally:
                conn.close()
            last_exc = None
            break
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if ("locked" in str(exc).lower() or "busy" in str(exc).lower()) and attempt < _SAVE_RETRIES - 1:
                time.sleep(0.2 * (attempt + 1))
                continue
            break
        except Exception as exc:
            last_exc = exc
            break
    if last_exc is not None:
        if _was_migrated(filename) is False:
            print(
                "[JSON-SQLite] WARNING: could not read %s from SQLite (%r); "
                "store was never migrated, falling back to the legacy JSON file."
                % (filename, last_exc)
            )
            return _read_legacy_file(filename)
        print(
            "[JSON-SQLite] ERROR: could not read %s from SQLite (%r); "
            "refusing the stale legacy fallback because the store is "
            "migrated (or its status is unknown)." % (filename, last_exc)
        )
        raise last_exc
    return _rows_to_dict(rows, table)


def save_store(filename, data):
    """Replace the store's contents with `data` (a dict), exactly
    like the old config.save_json() overwrote the whole file. Raises
    on persistent failure rather than silently forking data into the
    legacy JSON file."""
    if filename not in STORES:
        raise ValueError("No SQLite store for %r" % filename)
    if not isinstance(data, dict):
        raise TypeError("save_store expects a dict, got %r" % type(data))
    table, key_col = STORES[filename]
    # Serialise up front so a bad value fails before we touch the DB.
    encoded = {str(k): json.dumps(v) for k, v in data.items()}
    last_exc = None
    for attempt in range(_SAVE_RETRIES):
        try:
            conn = sqlite3.connect(_db_path(), timeout=30)
            try:
                conn.execute("BEGIN IMMEDIATE")
                _ensure_tables(conn)
                # Import legacy data first if this is the first ever
                # write, so a save that was never preceded by a load
                # cannot silently drop pre-migration rows.
                _migrate(conn, filename)
                conn.execute("DELETE FROM %s" % table)
                for key, raw in encoded.items():
                    conn.execute(
                        "INSERT INTO %s (%s, data) VALUES (?, ?)"
                        % (table, key_col),
                        (key, raw),
                    )
                conn.execute(
                    "INSERT OR IGNORE INTO json_migrations"
                    " (store, source_sha256, keys) VALUES (?, '', ?)",
                    (filename, len(encoded)),
                )
                conn.commit()
            finally:
                conn.close()
            return
        except sqlite3.OperationalError as exc:
            last_exc = exc
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                time.sleep(0.2 * (attempt + 1))
                continue
            print("[JSON-SQLite] ERROR: could not save %s: %r" % (filename, exc))
            raise
        except Exception as exc:
            print("[JSON-SQLite] ERROR: could not save %s: %r" % (filename, exc))
            raise
    print(
        "[JSON-SQLite] ERROR: could not save %s after %d attempts: %r"
        % (filename, _SAVE_RETRIES, last_exc)
    )
    raise last_exc


def store_status():
    """Read-only per-store status (no migration triggered). Used by
    the __main__ report and by manual checks."""
    status = {}
    db = _db_path()
    for filename, (table, key_col) in STORES.items():
        entry = {
            "table": table,
            "migrated": False,
            "rows": 0,
            "legacy_exists": os.path.exists(legacy_path(filename)),
            "backup_exists": os.path.exists(backup_path(filename)),
        }
        if os.path.exists(db):
            try:
                conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=10)
                try:
                    tables = {
                        r[0]
                        for r in conn.execute(
                            "SELECT name FROM sqlite_master WHERE type='table'"
                        ).fetchall()
                    }
                    if _MIGRATIONS_TABLE in tables:
                        entry["migrated"] = (
                            conn.execute(
                                "SELECT store FROM json_migrations WHERE store = ?",
                                (filename,),
                            ).fetchone()
                            is not None
                        )
                    if table in tables:
                        entry["rows"] = conn.execute(
                            "SELECT COUNT(*) FROM %s" % table
                        ).fetchone()[0]
                finally:
                    conn.close()
            except Exception:
                pass
        status[filename] = entry
    return status


if __name__ == "__main__":
    print("[JSON-SQLite] store status (db: %s)" % _db_path())
    for filename, entry in store_status().items():
        print(
            "  %s -> %s: migrated=%s rows=%d legacy=%s backup=%s"
            % (
                filename,
                entry["table"],
                entry["migrated"],
                entry["rows"],
                entry["legacy_exists"],
                entry["backup_exists"],
            )
        )
