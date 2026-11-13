"""Postgres storage for the Logger: cached messages + per-guild log
channels + the queryable event history.

(Same file, same class, same method names as the SQLite version --
only the storage engine changed, so web/services/logger_db.py and
the Logger cog need no changes.)

Connection model: one lazily-created psycopg connection, serialised
by a threading.Lock (the bot thread and the Flask web thread both
use the shared ``db`` instance). The connection is opened on FIRST
USE, not at import, and the schema is created once at that point,
so importing this module never fails when Postgres is briefly down.
The connection runs in autocommit: every single-statement write
commits at once (matching the old per-statement SQLite commits),
and the multi-statement prune runs inside one explicit transaction.

IDs are BIGINT (Discord snowflakes exceed 32-bit int) and
events.created_at is DOUBLE PRECISION (a REAL would lose ~7 bits of
an epoch timestamp). messages.created_at stays TEXT (an ISO string,
unchanged).
"""
import threading
import time

import psycopg
from psycopg.rows import dict_row

from data.DB.db import get_psycopg_conninfo


def _like_escape(value):
    """Escape LIKE wildcards so a filter matches literally."""
    return (str(value).replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


# Mirrors the old SQLite schema, with Postgres types. CREATE TABLE
# IF NOT EXISTS never touches an existing table.
_TABLE_DDL = (
    """
    CREATE TABLE IF NOT EXISTS messages(
        message_id BIGINT PRIMARY KEY,
        guild_id BIGINT,
        channel_id BIGINT,
        author_id BIGINT,
        author_name TEXT,
        content TEXT,
        attachments TEXT,
        created_at TEXT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guild_logs(
        guild_id BIGINT,
        log_type TEXT,
        channel_id BIGINT,
        PRIMARY KEY (guild_id, log_type)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS log_toggles(
        guild_id BIGINT,
        event_key TEXT,
        enabled INTEGER,
        PRIMARY KEY (guild_id, event_key)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS events(
        id BIGSERIAL PRIMARY KEY,
        guild_id BIGINT NOT NULL,
        category TEXT NOT NULL,
        event_type TEXT,
        summary TEXT,
        created_at DOUBLE PRECISION NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_events_guild_time
    ON events(guild_id, created_at DESC)
    """,
)


class LoggerDatabase:
    """Thread-safe wrapper around the logger Postgres database."""

    def __init__(self):
        self._lock = threading.Lock()
        self._conn = None
        self._ready = False

    def _ensure(self):
        """Return a live connection, creating it (and the schema) on
        first use. Caller must hold self._lock. A connection that was
        closed (e.g. Postgres restarted) is reopened; the schema
        step runs only once per process.
        """
        if self._conn is None or self._conn.closed:
            self._conn = psycopg.connect(
                get_psycopg_conninfo(), row_factory=dict_row,
                autocommit=True,
            )
            self._ready = False
        if not self._ready:
            cur = self._conn.cursor()
            for ddl in _TABLE_DDL:
                cur.execute(ddl)
            cur.close()
            self._ready = True
        return self._conn

    # ----- message cache -----

    def save_message(self, message):
        """Cache a message so deletes/edits can show its original content."""
        if message.guild is None:
            return
        attachments = ",".join(a.url for a in message.attachments)
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO messages VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (message_id) DO UPDATE SET "
                "guild_id = EXCLUDED.guild_id, "
                "channel_id = EXCLUDED.channel_id, "
                "author_id = EXCLUDED.author_id, "
                "author_name = EXCLUDED.author_name, "
                "content = EXCLUDED.content, "
                "attachments = EXCLUDED.attachments, "
                "created_at = EXCLUDED.created_at",
                (
                    message.id,
                    message.guild.id,
                    message.channel.id,
                    message.author.id,
                    str(message.author),
                    message.content or "",
                    attachments,
                    message.created_at.isoformat(),
                ),
            )

    def get_message(self, message_id):
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                "SELECT * FROM messages WHERE message_id = %s", (message_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_message(self, message_id):
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "DELETE FROM messages WHERE message_id = %s", (message_id,)
            )

    # ----- log channel config -----

    def set_log_channel(self, guild_id, log_type, channel_id):
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO guild_logs (guild_id, log_type, channel_id)"
                " VALUES (%s, %s, %s) "
                "ON CONFLICT (guild_id, log_type) DO UPDATE SET "
                "channel_id = EXCLUDED.channel_id",
                (guild_id, log_type, channel_id),
            )

    def get_log_channel(self, guild_id, log_type):
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                "SELECT channel_id FROM guild_logs WHERE guild_id = %s AND log_type = %s",
                (guild_id, log_type),
            ).fetchone()
            return row["channel_id"] if row else None

    def is_enabled(self, guild_id, event_key):
        """True unless the guild explicitly disabled this event."""
        with self._lock:
            conn = self._ensure()
            row = conn.execute(
                "SELECT enabled FROM log_toggles WHERE guild_id = %s AND event_key = %s",
                (guild_id, event_key),
            ).fetchone()
            return bool(row["enabled"]) if row else True

    def set_enabled(self, guild_id, event_key, enabled):
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO log_toggles (guild_id, event_key, enabled)"
                " VALUES (%s, %s, %s) "
                "ON CONFLICT (guild_id, event_key) DO UPDATE SET "
                "enabled = EXCLUDED.enabled",
                (guild_id, event_key, 1 if enabled else 0),
            )

    def get_all_log_channels(self, guild_id):
        """Return {log_type: channel_id} for a guild."""
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                "SELECT log_type, channel_id FROM guild_logs WHERE guild_id = %s",
                (guild_id,),
            ).fetchall()
            return {row["log_type"]: row["channel_id"] for row in rows}

    # ----- event history (web dashboard) -----

    def record_event(self, guild_id, category, event_type, summary):
        """Append to the queryable event history (last 5000 per guild kept).

        P1-25: insert only. The per-event prune DELETE used to run here
        on every logged event, scanning the events table on the gateway
        loop. Retention is now enforced by the periodic sweep in
        LoggerCommands._prune_event_history, which calls prune_events().
        """
        with self._lock:
            conn = self._ensure()
            conn.execute(
                "INSERT INTO events(guild_id, category, event_type, summary, created_at)"
                " VALUES(%s,%s,%s,%s,%s)",
                (guild_id, category, event_type, summary, time.time()),
            )

    def prune_events(self, keep=5000):
        """Trim every guild's event history to the newest `keep` rows.

        P1-25: called by the periodic sweep in LoggerCommands, not on
        every event. Returns the number of rows deleted.
        """
        with self._lock:
            conn = self._ensure()
            with conn.transaction():
                guild_ids = [
                    row["guild_id"]
                    for row in conn.execute(
                        "SELECT DISTINCT guild_id FROM events"
                    ).fetchall()
                ]
                deleted = 0
                for guild_id in guild_ids:
                    cur = conn.execute(
                        "DELETE FROM events WHERE guild_id=%s AND id NOT IN"
                        " (SELECT id FROM events WHERE guild_id=%s ORDER BY id DESC LIMIT %s)",
                        (guild_id, guild_id, keep),
                    )
                    deleted += cur.rowcount
            return deleted

    def _event_filter(self, guild_id, category=None, event_type=None, search=None,
                      user_id=None, channel_id=None, date_from=None, date_to=None):
        """WHERE fragment for the events table.

        The events table has no user/channel columns: user_id and
        channel_id match against the recorded summary text, which
        carries raw IDs (mentions, backticked IDs, author lines) for
        events recorded after the Logger summary enrichment. Rows with
        a NULL summary never match a user/channel filter. date_from
        and date_to are epoch seconds (date_to is exclusive).
        """
        q = "FROM events WHERE guild_id=%s"
        args = [guild_id]
        if category:
            q += " AND category=%s"
            args.append(category)
        if event_type:
            q += " AND event_type=%s"
            args.append(event_type)
        if search:
            q += " AND summary LIKE %s ESCAPE '\\'"
            args.append(f"%{_like_escape(search)}%")
        if user_id and str(user_id).isdigit():
            q += " AND summary LIKE %s ESCAPE '\\'"
            args.append(f"%{user_id}%")
        if channel_id and str(channel_id).isdigit():
            q += " AND summary LIKE %s ESCAPE '\\'"
            args.append(f"%{channel_id}%")
        if date_from is not None:
            q += " AND created_at >= %s"
            args.append(float(date_from))
        if date_to is not None:
            q += " AND created_at < %s"
            args.append(float(date_to))
        return q, args

    def query_events(self, guild_id, category=None, event_type=None, search=None,
                     limit=50, offset=0, user_id=None, channel_id=None,
                     date_from=None, date_to=None):
        """Event history newest-first. Used by the web dashboard."""
        filt, args = self._event_filter(
            guild_id, category=category, event_type=event_type, search=search,
            user_id=user_id, channel_id=channel_id,
            date_from=date_from, date_to=date_to,
        )
        with self._lock:
            conn = self._ensure()
            rows = conn.execute(
                f"SELECT id, guild_id, category, event_type, summary, created_at "
                f"{filt} ORDER BY id DESC LIMIT %s OFFSET %s",
                args + [limit, offset],
            ).fetchall()
            return [dict(r) for r in rows]

    def count_events(self, guild_id, category=None, event_type=None, search=None,
                     user_id=None, channel_id=None, date_from=None, date_to=None):
        filt, args = self._event_filter(
            guild_id, category=category, event_type=event_type, search=search,
            user_id=user_id, channel_id=channel_id,
            date_from=date_from, date_to=date_to,
        )
        with self._lock:
            conn = self._ensure()
            row = conn.execute(f"SELECT COUNT(*) AS n {filt}", args).fetchone()
            return row["n"]


# Shared instance. Created lazily on first import; the Postgres
# connection itself is opened on first use (see _ensure).
db = LoggerDatabase()
