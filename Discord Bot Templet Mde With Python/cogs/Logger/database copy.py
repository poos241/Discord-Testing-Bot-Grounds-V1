import json
import sqlite3

DATABASE = "data/message_log.db"


class LoggerDatabase:

    def __init__(self):

        self.connection = sqlite3.connect(

            DATABASE,

            check_same_thread=False

        )

        self.cursor = self.connection.cursor()

        self.cursor.execute("""

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

        self.connection.commit()
        
        self.cursor.execute("""
                            
        CREATE TABLE IF NOT EXISTS logger_events

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            guild_id INTEGER,

            category TEXT,

            payload TEXT,

            created INTEGER

        """)

    def save(self, message):

        attachments = ",".join(

            a.url

            for a in message.attachments

        )

        self.cursor.execute("""

        INSERT OR REPLACE INTO messages

        VALUES(

        ?,?,?,?,?,?,?,?

        )

        """, (

            message.id,

            message.guild.id,

            message.channel.id,

            message.author.id,

            str(message.author),

            message.content,

            attachments,

            message.created_at.isoformat()

        ))

        self.connection.commit()

    def fetch(self, message_id):

        self.cursor.execute(

            """

            SELECT *

            FROM messages

            WHERE message_id=?

            """,

            (

                message_id,

            )

        )

        return self.cursor.fetchone()

    def delete(self, message_id):

        self.cursor.execute(

            """

            DELETE FROM messages

            WHERE message_id=?

            """,

            (

                message_id,

            )

        )

        self.connection.commit()
        
        
    def save_event(

    self,

    guild_id,

    category,

    payload

    ):

        self.cursor.execute(

            """

            INSERT INTO logger_events

            (

                guild_id,

                category,

                payload,

                created

            )

            VALUES

            (?, ?, ?, strftime('%s','now'))

            """,

            (

                guild_id,

                category,

                json.dumps(payload)

            )

        )

        self.connection.commit()


database = LoggerDatabase()