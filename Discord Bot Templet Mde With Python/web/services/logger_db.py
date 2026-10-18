"""Adapter over the Logger's real database (``cogs/Logger/database.py``).

Web blueprints/services written against the old Logger DB import this
module as ``database``. It exposes the query shapes they expect, backed
by the real ``events`` table.
"""

import time


def _db():
    from cogs.Logger.database import db
    return db


class _LoggerDbAdapter:
    """Thin adapter: old call shapes, new ``events`` table underneath."""

    # ----- passthroughs that exist on the real db -----
    def get_log_channel(self, guild_id, log_type):
        return _db().get_log_channel(guild_id, log_type)

    def set_log_channel(self, guild_id, log_type, channel_id):
        return _db().set_log_channel(guild_id, log_type, channel_id)

    def get_all_log_channels(self, guild_id):
        return _db().get_all_log_channels(guild_id)

    def is_enabled(self, guild_id, event_key):
        return _db().is_enabled(guild_id, event_key)

    # ----- event history -----
    def latest_global_events(self, limit=100):
        # No cross-guild query on the real db; return empty (callers
        # should pass a guild_id).
        return []

    def count_events(self, guild_id, search=None, category=None):
        return _db().count_events(guild_id, category=category, search=search)

    def search_events(self, guild_id, search=None, category=None,
                      event_type=None, limit=50, offset=0):
        return _db().query_events(
            guild_id, category=category, event_type=event_type,
            search=search, limit=limit, offset=offset,
        )

    def get_event(self, guild_id, event_id):
        for e in _db().query_events(guild_id, limit=5000):
            if e["id"] == event_id:
                return e
        return None

    def save_event_from_bot(self, **kwargs):
        # The Logger cog records events itself in Logger.send.
        return None

    @property
    def connection(self):
        # Compat: old code used database.connection.cursor().
        return _db()._conn


logger_db = _LoggerDbAdapter()
# Old import style: ``from web.services.logger_db import logger_db as database``
database = logger_db
