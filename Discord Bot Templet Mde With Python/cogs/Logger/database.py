"""SQLite storage for the Logger: cached messages + per-guild log channels."""
import os
import sqlite3
import threading

DB_PATH = os.path.normpath(os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "data", "message_log.db"
))


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
db = LoggerDatabase()
