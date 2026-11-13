# utils/json_sqlite_store.py
#
# Sync Postgres backing store for the bot's remaining JSON data files.
#
# (The filename is historical -- this was the SQLite store before the
# Postgres migration. It is kept so the existing imports in config.py
# and the cogs keep working unchanged.)
#
# Why this module exists: mod_data, watchlist, and the eatyeet_* files
# were the last JSON stores left after profiles moved to SQLite. Every
# reader/writer of those files goes through config.load_json/save_json,
# which are synchronous (cog __init__, Flask routes, background sweeps),
# so the async `databases` helpers in data/DB/Storage/storage.py cannot
# be used here without rewriting dozens of call sites. This module keeps
# the exact same dict API (load -> dict, save(dict)) but stores the data
# in Postgres using psycopg (sync), the same database the rest of the
# bot uses.
#
# Schema: one row per top-level key, in tables declared in
# data/DB/models.py (the canonical schema; the CREATE TABLE IF NOT
# EXISTS statements here mirror it so the store also works before
# data/DB/db.py's create_all() runs, and they never alter an existing
# table). Values are JSONB in a `data` column, the same shape the
# old files held -- the same JSON-blob pattern the `levels` table
# already uses. The json_quarantine table is NOT in models.py; it is
# created by _ensure_tables() here, exactly as before.
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
# absent). Once migrated, a persistent Postgres read failure raises
# instead of returning the frozen pre-migration file: returning it
# would let the next save overwrite the live table with stale data.
#
# Failed import (P2-44): if the legacy file cannot be parsed, the
# store is NOT marked migrated -- the migration row is only recorded
# after a successful import, and the failed import is logged loudly.
# The legacy file is then retried on the next load/save, so fixing the
# file (or removing it) recovers the data instead of losing it
# forever behind a bogus "migrated" row. The save itself still
# proceeds (it writes the live in-memory rows); only the migration
# marker is withheld.
#
# Rollback: restore the pre-migration copies of config.py (and the
# other edited .py files) and the bot will read the JSON files again.
# The JSON files still hold their pre-migration contents, so nothing
# written before the migration is lost -- but note that anything
# written to Postgres AFTER migration is not in the JSON files, so a
# rollback discards post-migration changes. That is the same trade-off
# the profiles migration had.
#
# Corrupt rows (P2-46): a row whose `data` is not valid JSON used to be
# silently skipped on load and then permanently deleted by the next
# save (save_store DELETEs the whole table and re-inserts only the
# parsed rows). Now an unreadable row is QUARANTINED instead: its raw
# text is kept in the json_quarantine table, the load still returns the
# readable rows, and save_store REFUSES to save that store until every
# quarantined key is present again in the data being saved. Repair
# path: fix the row's JSON directly in Postgres (UPDATE <table> SET
# data='<valid json>'::jsonb WHERE <key_col>='<key>'); the next load
# parses it, the next save includes the key and clears the quarantine
# row. If the row is junk, delete its quarantine row with
# DELETE FROM json_quarantine WHERE store='<file>' AND "key"='<key>'
# and the store saves normally again. store_status() reports the
# quarantined key count per store; quarantined_rows() returns the raw
# text for inspection.
#
# Postgres JSONB note (the NUMERIC-affinity quirk, fixed): on SQLite
# a bare-number top-level value stored as INTEGER made json.loads
# raise TypeError and the row was quarantined. Postgres JSONB returns
# real values, not strings -- a stored number comes back as a Python
# int, a stored object as a dict -- so _rows_to_dict accepts BOTH a
# string (json.loads it) and an already-parsed value (uses it
# directly). Only a NULL data column is still treated as unreadable.
#
# Concurrency: every call opens its own short-lived psycopg
# connection (never shared across threads -- the bot thread and the
# Flask web thread both use this module). Postgres serialises
# concurrent writers on row locks, so there is no BEGIN IMMEDIATE and
# no lock-retry loop: a single transaction per call is enough.

import hashlib
import json
import os

import psycopg

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

# Quarantine for rows whose `data` is not valid JSON (P2-46). One row
# per corrupt (store, key); `raw` keeps the exact unreadable text so
# it can be inspected and repaired instead of being deleted by the
# next save. `first_seen` is kept across re-quarantines (UPSERT below
# only refreshes raw/error).
_QUARANTINE_TABLE = "json_quarantine"

# Mirrors data/DB/models.py (canonical schema) for the six store
# tables and json_migrations, plus json_quarantine (which lives only
# here). CREATE TABLE IF NOT EXISTS never touches an existing table.
# `"key"` is quoted because KEY is a keyword; quoting keeps it an
# ordinary column name.
_TABLE_DDL = {
    "mod_data": (
        "CREATE TABLE IF NOT EXISTS mod_data ("
        "guild_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    "watchlist_data": (
        "CREATE TABLE IF NOT EXISTS watchlist_data ("
        "guild_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    "eatyeet_stats": (
        "CREATE TABLE IF NOT EXISTS eatyeet_stats ("
        "guild_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    "eatyeet_suggestions": (
        "CREATE TABLE IF NOT EXISTS eatyeet_suggestions ("
        "guild_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    "eatyeet_active": (
        "CREATE TABLE IF NOT EXISTS eatyeet_active ("
        "channel_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    "eatyeet_rematch": (
        "CREATE TABLE IF NOT EXISTS eatyeet_rematch ("
        "channel_id VARCHAR PRIMARY KEY, data JSONB, "
        "created_at TIMESTAMP DEFAULT now(), "
        "updated_at TIMESTAMP DEFAULT now())"
    ),
    _MIGRATIONS_TABLE: (
        "CREATE TABLE IF NOT EXISTS json_migrations ("
        "store VARCHAR PRIMARY KEY, "
        "migrated_at TIMESTAMP DEFAULT now(), "
        "source_sha256 VARCHAR DEFAULT '', keys INTEGER DEFAULT 0)"
    ),
    _QUARANTINE_TABLE: (
        "CREATE TABLE IF NOT EXISTS json_quarantine ("
        "store VARCHAR, \"key\" VARCHAR, raw TEXT, "
        "error VARCHAR DEFAULT '', "
        "first_seen TIMESTAMP DEFAULT now(), "
        "PRIMARY KEY (store, \"key\"))"
    ),
}


def _connect():
    """A fresh psycopg connection (new per call; never shared across
    threads). The conninfo comes from data.DB.db, resolved lazily
    here so importing this module never fails when the database is
    briefly unavailable -- only actual use needs DATABASE_URL."""
    from data.DB.db import get_psycopg_conninfo

    return psycopg.connect(get_psycopg_conninfo())


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
        "SELECT store FROM json_migrations WHERE store = %s", (filename,)
    ).fetchone()
    if row is not None:
        return True
    table, _key_col = STORES[filename]
    legacy = legacy_path(filename)
    if not os.path.exists(legacy):
        conn.execute(
            "INSERT INTO json_migrations (store, source_sha256, keys)"
            " VALUES (%s, '', 0) ON CONFLICT (store) DO NOTHING",
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
                "[JSON-PG] WARNING: legacy %s is not valid JSON; "
                "leaving it unmigrated (Postgres store starts empty)."
                % filename
            )
            return False
    if not isinstance(parsed, dict):
        print(
            "[JSON-PG] WARNING: legacy %s is not a JSON object; "
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
            "INSERT INTO %s (%s, data) VALUES (%%s, %%s) "
            "ON CONFLICT (%s) DO UPDATE SET data = EXCLUDED.data, "
            "updated_at = now()" % (table, STORES[filename][1], STORES[filename][1]),
            (str(key), json.dumps(value)),
        )
    conn.execute(
        "INSERT INTO json_migrations (store, source_sha256, keys)"
        " VALUES (%s, %s, %s)",
        (filename, hashlib.sha256(raw).hexdigest(), len(parsed)),
    )
    print(
        "[JSON-PG] Migrated %s -> %s (%d keys; backup kept at %s)"
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
        conn = _connect()
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                ).fetchall()
            }
            if _MIGRATIONS_TABLE not in tables:
                return False
            return (
                conn.execute(
                    "SELECT store FROM json_migrations WHERE store = %s",
                    (filename,),
                ).fetchone()
                is not None
            )
        finally:
            conn.close()
    except Exception:
        return None


def _rows_to_dict(rows, table):
    """Parse SELECT (key, data) rows into a dict.

    Returns (parsed_dict, bad_rows) where bad_rows is a list of
    (key, raw_text, error) for rows whose `data` is not valid JSON.
    Bad rows are NOT in the dict -- they cannot be parsed -- but the
    caller must quarantine them (see _quarantine_rows) instead of
    dropping them, or the next save would delete them forever (P2-46).

    Postgres JSONB returns real values, not strings, so a `data`
    that is already a dict / list / number / bool is used directly;
    only a string is passed through json.loads, and only a NULL is
    unreadable. (On SQLite a bare-number value came back as an
    INTEGER and json.loads raised TypeError, quarantining a
    perfectly good row -- that quirk is gone.)
    """
    out = {}
    bad = []
    for key, raw in rows:
        if isinstance(raw, str):
            try:
                out[key] = json.loads(raw)
            except ValueError as exc:
                bad.append((key, raw, str(exc)))
                print(
                    "[JSON-PG] ERROR: unreadable row %r in %s (%s); "
                    "quarantining the raw text instead of dropping it."
                    % (key, table, exc)
                )
        elif raw is None:
            bad.append((key, "", "data is NULL"))
            print(
                "[JSON-PG] ERROR: unreadable row %r in %s (data is NULL); "
                "quarantining instead of dropping it." % (key, table)
            )
        else:
            out[key] = raw
    return out, bad


def _quarantine_rows(conn, filename, bad):
    """Keep the raw text of unreadable rows in json_quarantine.

    Must be called inside a write transaction; commits nothing
    itself. Re-quarantining a key refreshes its raw text and error
    but keeps the original first_seen, so the first time the
    corruption was noticed is not lost.
    """
    for key, raw_text, error in bad:
        conn.execute(
            "INSERT INTO %s (store, \"key\", raw, error) VALUES (%%s, %%s, %%s, %%s) "
            "ON CONFLICT (store, \"key\") DO UPDATE SET raw = EXCLUDED.raw, "
            "error = EXCLUDED.error" % _QUARANTINE_TABLE,
            (filename, str(key), raw_text, error[:500]),
        )


def _quarantined_keys(conn, filename):
    """Keys currently quarantined for this store (read inside a
    transaction on `conn`)."""
    return {
        r[0]
        for r in conn.execute(
            "SELECT \"key\" FROM %s WHERE store = %%s" % _QUARANTINE_TABLE,
            (filename,),
        ).fetchall()
    }


def quarantined_rows(filename):
    """Read-only list of quarantined rows for a store: dicts with
    key, raw (the exact unreadable text), error, and first_seen.
    Used by store_status()/debug to surface corrupt rows (P2-46)."""
    if filename not in STORES:
        raise ValueError("No Postgres store for %r" % filename)
    try:
        conn = _connect()
        try:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = current_schema()"
                ).fetchall()
            }
            if _QUARANTINE_TABLE not in tables:
                return []
            return [
                {
                    "key": key,
                    "raw": raw,
                    "error": error,
                    "first_seen": first_seen,
                }
                for key, raw, error, first_seen in conn.execute(
                    "SELECT \"key\", raw, error, first_seen FROM %s "
                    "WHERE store = %%s ORDER BY \"key\"" % _QUARANTINE_TABLE,
                    (filename,),
                ).fetchall()
            ]
        finally:
            conn.close()
    except Exception:
        return []


def _load_store_readonly(filename, table, key_col):
    """Read a migrated store without a write transaction.

    Returns the rows when the store's table exists and its migration
    row is present, else None (caller falls through to the write
    path, which creates/migrates). Raises on any other failure so the
    caller can fall through too -- the write path owns the retries
    and the legacy-fallback decision. Postgres reads never block
    writers (MVCC), so unlike the SQLite version this needs no
    read-only connection mode: a plain SELECT is the fast path.
    """
    conn = _connect()
    try:
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = current_schema()"
            ).fetchall()
        }
        if table not in tables or _MIGRATIONS_TABLE not in tables:
            return None
        row = conn.execute(
            "SELECT store FROM json_migrations WHERE store = %s",
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

    On a persistent failure the legacy file is returned ONLY when the
    store was never migrated; once migrated (or when migration status
    cannot be established) this raises instead of returning the frozen
    pre-migration file, because the next save would overwrite the live
    table with that stale data.
    """
    if filename not in STORES:
        raise ValueError("No Postgres store for %r" % filename)
    table, key_col = STORES[filename]
    # Fast path: when the schema is ready and this store is migrated,
    # read with a plain SELECT, so a load can never stall behind (or
    # block) a writer. Postgres reads do not take write locks, so
    # this is just a connection + SELECT, no special mode needed.
    try:
        rows = _load_store_readonly(filename, table, key_col)
        if rows is not None:
            data, bad = _rows_to_dict(rows, table)
            if not bad:
                return data
            # Unreadable rows: the read-only connection cannot
            # quarantine them, so fall through to the write path
            # below, which re-reads and quarantines in-transaction.
            # The load still returns the readable rows; the corrupt
            # ones are preserved in json_quarantine, not dropped.
            print(
                "[JSON-PG] WARNING: %s has %d unreadable row(s); "
                "quarantining via the write path." % (filename, len(bad))
            )
    except Exception as exc:
        # P3-39: the fast path used to fail silently, so a degrading
        # store looked healthy until the write path also failed. Log
        # at debug level (a fall-through here is expected/transient
        # by design -- the write path owns the retries) and fall
        # through to the write path below.
        print(
            "[JSON-PG] DEBUG: fast-path load of %s failed (%r); "
            "falling through to the write path." % (filename, exc)
        )
    data = None
    last_exc = None
    try:
        conn = _connect()
        try:
            with conn.transaction():
                _ensure_tables(conn)
                _migrate(conn, filename)
                rows = conn.execute(
                    "SELECT %s, data FROM %s ORDER BY %s" % (key_col, table, key_col)
                ).fetchall()
                data, bad = _rows_to_dict(rows, table)
                if bad:
                    # Same transaction as the read: the raw text is
                    # preserved before any later save can delete it.
                    _quarantine_rows(conn, filename, bad)
        finally:
            conn.close()
    except Exception as exc:
        last_exc = exc
    if last_exc is not None:
        if _was_migrated(filename) is False:
            print(
                "[JSON-PG] WARNING: could not read %s from Postgres (%r); "
                "store was never migrated, falling back to the legacy JSON file."
                % (filename, last_exc)
            )
            return _read_legacy_file(filename)
        print(
            "[JSON-PG] ERROR: could not read %s from Postgres (%r); "
            "refusing the stale legacy fallback because the store is "
            "migrated (or its status is unknown)." % (filename, last_exc)
        )
        raise last_exc
    return data


def save_store(filename, data):
    """Replace the store's contents with `data` (a dict), exactly
    like the old config.save_json() overwrote the whole file. Raises
    on persistent failure rather than silently forking data into the
    legacy JSON file.

    Also raises RuntimeError (P2-46) when the store has quarantined
    rows -- rows whose `data` was unreadable on load -- that are not
    present in `data`: writing would DELETE those rows forever. Fix
    the row's JSON in Postgres first (then it loads, is present in the
    next save, and its quarantine row is cleared), or delete the
    json_quarantine row if the data is junk."""
    if filename not in STORES:
        raise ValueError("No Postgres store for %r" % filename)
    if not isinstance(data, dict):
        raise TypeError("save_store expects a dict, got %r" % type(data))
    table, key_col = STORES[filename]
    # Serialise up front so a bad value fails before we touch the DB.
    encoded = {str(k): json.dumps(v) for k, v in data.items()}
    try:
        conn = _connect()
        try:
            with conn.transaction():
                _ensure_tables(conn)
                # Import legacy data first if this is the first ever
                # write, so a save that was never preceded by a load
                # cannot silently drop pre-migration rows.
                # P2-44: _migrate returns False when the legacy file
                # exists but cannot be parsed. In that case do NOT
                # record the migration row below -- marking a
                # never-imported store "migrated" would make the
                # legacy file never be retried (and would stop
                # load_store ever falling back to it). The save
                # itself still proceeds; only the marker is
                # withheld, and the import is retried on the next
                # load/save once the file is fixed or removed.
                migrated = _migrate(conn, filename)
                if not migrated:
                    print(
                        "[JSON-PG] ERROR: legacy %s could not be "
                        "imported; NOT marking %s migrated -- the "
                        "legacy file will be retried on the next "
                        "load/save. Fix or remove the file to stop "
                        "this warning." % (filename, filename)
                    )
                # P2-46: never let a save delete a quarantined row.
                # A store whose load dropped rows is missing those
                # keys from `data`; writing it would DELETE the
                # corrupt row from the table forever. Refuse unless
                # the incoming data repairs every quarantined key
                # (carries a fresh value for it); repaired keys have
                # their quarantine rows cleared in this transaction.
                # (Raising here rolls the transaction back, so no
                # live row is touched.)
                missing = _quarantined_keys(conn, filename) - set(encoded)
                if missing:
                    raise RuntimeError(
                        "Refusing to save %s: %d quarantined row(s) "
                        "would be deleted (%s). Repair the row(s) in "
                        "Postgres, or delete their json_quarantine "
                        "rows if the data is junk; see the header of "
                        "utils/json_sqlite_store.py."
                        % (filename, len(missing), sorted(missing)[:5])
                    )
                conn.execute(
                    "DELETE FROM %s WHERE store = %%s" % _QUARANTINE_TABLE,
                    (filename,),
                )
                conn.execute("DELETE FROM %s" % table)
                for key, raw in encoded.items():
                    conn.execute(
                        "INSERT INTO %s (%s, data) VALUES (%%s, %%s)"
                        % (table, key_col),
                        (key, raw),
                    )
                # P2-44: only record the migration row when the
                # import actually succeeded (or the store was
                # already migrated / had no legacy file). When
                # _migrate returned False the legacy file was never
                # imported, so inserting this row would falsely mark
                # the store migrated and the file would never be
                # retried. (_migrate already inserts the row in
                # every success case, so this is belt-and-braces.)
                if migrated:
                    conn.execute(
                        "INSERT INTO json_migrations"
                        " (store, source_sha256, keys) VALUES (%s, '', %s)"
                        " ON CONFLICT (store) DO NOTHING",
                        (filename, len(encoded)),
                    )
        finally:
            conn.close()
    except Exception as exc:
        print("[JSON-PG] ERROR: could not save %s: %r" % (filename, exc))
        raise


def store_status():
    """Read-only per-store status (no migration triggered). Used by
    the __main__ report and by manual checks."""
    status = {}
    for filename, (table, key_col) in STORES.items():
        entry = {
            "table": table,
            "migrated": False,
            "rows": 0,
            "quarantined": 0,
            "quarantined_keys": [],
            "legacy_exists": os.path.exists(legacy_path(filename)),
            "backup_exists": os.path.exists(backup_path(filename)),
        }
        try:
            conn = _connect()
            try:
                tables = {
                    r[0]
                    for r in conn.execute(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = current_schema()"
                    ).fetchall()
                }
                if _MIGRATIONS_TABLE in tables:
                    entry["migrated"] = (
                        conn.execute(
                            "SELECT store FROM json_migrations WHERE store = %s",
                            (filename,),
                        ).fetchone()
                        is not None
                    )
                if table in tables:
                    entry["rows"] = conn.execute(
                        "SELECT COUNT(*) FROM %s" % table
                    ).fetchone()[0]
                if _QUARANTINE_TABLE in tables:
                    # P2-46: surface corrupt rows instead of
                    # silently dropping them on the next save.
                    quarantined = conn.execute(
                        "SELECT \"key\" FROM %s WHERE store = %%s ORDER BY \"key\""
                        % _QUARANTINE_TABLE,
                        (filename,),
                    ).fetchall()
                    entry["quarantined"] = len(quarantined)
                    entry["quarantined_keys"] = [r[0] for r in quarantined]
            finally:
                conn.close()
        except Exception:
            pass
        status[filename] = entry
    return status


if __name__ == "__main__":
    print("[JSON-PG] store status (Postgres)")
    for filename, entry in store_status().items():
        print(
            "  %s -> %s: migrated=%s rows=%d quarantined=%d %s legacy=%s backup=%s"
            % (
                filename,
                entry["table"],
                entry["migrated"],
                entry["rows"],
                entry["quarantined"],
                entry["quarantined_keys"],
                entry["legacy_exists"],
                entry["backup_exists"],
            )
        )
