"""SQLite storage for the Logger: cached messages + per-guild log channels."""
import os
import sqlite3
import threading

DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "message_log.db"
))


def _like_escape(value):
    """Escape LIKE wildcards so a filter matches literally."""
    return (str(value).replace("\\", "\\\\")
            .replace("%", "\\%").replace("_", "\\_"))


class LoggerDatabase:
    """Thread-safe wrapper around the logger SQLite database."""

    def __init__(self):
        self._lock = threading.Lock()
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        self._conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            cur = self._conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS messages(
                    message_id INTEGER PRIMARY KEY,
                    guild_id INTEGER,
                    channel_id INTEGER,
                    author_id INTEGER,
                    author_name TEXT,
                    content TEXT,
                    attachments TEXT,
                    created_at TEXT
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS guild_logs(
                    guild_id INTEGER,
                    log_type TEXT,
                    channel_id INTEGER,
                    PRIMARY KEY (guild_id, log_type)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS log_toggles(
                    guild_id INTEGER,
                    event_key TEXT,
                    enabled INTEGER,
                    PRIMARY KEY (guild_id, event_key)
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_id INTEGER NOT NULL,
                    category TEXT NOT NULL,
                    event_type TEXT,
                    summary TEXT,
                    created_at REAL NOT NULL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_guild_time
                ON events(guild_id, created_at DESC)
            """)
            self._conn.commit()

    # ----- message cache -----

    def save_message(self, message):
        """Cache a message so deletes/edits can show its original content."""
        if message.guild is None:
            return
        attachments = ",".join(a.url for a in message.attachments)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO messages VALUES (?,?,?,?,?,?,?,?)",
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
            self._conn.commit()

    def get_message(self, message_id):
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM messages WHERE message_id = ?", (message_id,)
            )
            row = cur.fetchone()
            return dict(row) if row else None

    def delete_message(self, message_id):
        with self._lock:
            self._conn.execute(
                "DELETE FROM messages WHERE message_id = ?", (message_id,)
            )
            self._conn.commit()

    # ----- log channel config -----

    def set_log_channel(self, guild_id, log_type, channel_id):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO guild_logs (guild_id, log_type, channel_id)"
                " VALUES (?, ?, ?)",
                (guild_id, log_type, channel_id),
            )
            self._conn.commit()

    def get_log_channel(self, guild_id, log_type):
        with self._lock:
            cur = self._conn.execute(
                "SELECT channel_id FROM guild_logs WHERE guild_id = ? AND log_type = ?",
                (guild_id, log_type),
            )
            row = cur.fetchone()
            return row["channel_id"] if row else None

    def is_enabled(self, guild_id, event_key):
        """True unless the guild explicitly disabled this event."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT enabled FROM log_toggles WHERE guild_id = ? AND event_key = ?",
                (guild_id, event_key),
            )
            row = cur.fetchone()
            return bool(row["enabled"]) if row else True

    def set_enabled(self, guild_id, event_key, enabled):
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO log_toggles (guild_id, event_key, enabled)"
                " VALUES (?, ?, ?)",
                (guild_id, event_key, 1 if enabled else 0),
            )
            self._conn.commit()

    def get_all_log_channels(self, guild_id):
        """Return {log_type: channel_id} for a guild."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT log_type, channel_id FROM guild_logs WHERE guild_id = ?",
                (guild_id,),
            )
            return {row["log_type"]: row["channel_id"] for row in cur.fetchall()}


# Shared instance. Created lazily on first import; uses an absolute path.
    # ----- event history (web dashboard) -----

    def record_event(self, guild_id, category, event_type, summary):
        """Append to the queryable event history (last 5000 per guild kept)."""
        import time
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(
                "INSERT INTO events(guild_id, category, event_type, summary, created_at)"
                " VALUES(?,?,?,?,?)",
                (guild_id, category, event_type, summary, time.time()),
            )
            cur.execute(
                "DELETE FROM events WHERE guild_id=? AND id NOT IN"
                " (SELECT id FROM events WHERE guild_id=? ORDER BY id DESC LIMIT 5000)",
                (guild_id, guild_id),
            )
            self._conn.commit()

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
        q = "FROM events WHERE guild_id=?"
        args = [guild_id]
        if category:
            q += " AND category=?"
            args.append(category)
        if event_type:
            q += " AND event_type=?"
            args.append(event_type)
        if search:
            q += " AND summary LIKE ? ESCAPE '\\'"
            args.append(f"%{_like_escape(search)}%")
        if user_id and str(user_id).isdigit():
            q += " AND summary LIKE ? ESCAPE '\\'"
            args.append(f"%{user_id}%")
        if channel_id and str(channel_id).isdigit():
            q += " AND summary LIKE ? ESCAPE '\\'"
            args.append(f"%{channel_id}%")
        if date_from is not None:
            q += " AND created_at >= ?"
            args.append(float(date_from))
        if date_to is not None:
            q += " AND created_at < ?"
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
            cur = self._conn.cursor()
            cur.execute(
                f"SELECT id, guild_id, category, event_type, summary, created_at "
                f"{filt} ORDER BY id DESC LIMIT ? OFFSET ?",
                args + [limit, offset],
            )
            return [dict(r) for r in cur.fetchall()]

    def count_events(self, guild_id, category=None, event_type=None, search=None,
                     user_id=None, channel_id=None, date_from=None, date_to=None):
        filt, args = self._event_filter(
            guild_id, category=category, event_type=event_type, search=search,
            user_id=user_id, channel_id=channel_id,
            date_from=date_from, date_to=date_to,
        )
        with self._lock:
            cur = self._conn.cursor()
            cur.execute(f"SELECT COUNT(*) AS n {filt}", args)
            return cur.fetchone()["n"]

db = LoggerDatabase()
