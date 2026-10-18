"""Stub for the old ``cogs.Logger.database`` module.

TODO(webui): re-point at the new Logger schema (the working bot's
``data/message_log.db``). This stub keeps every blueprint importable and
returns empty data so pages render. Implement these methods against the
real schema instead of editing every call site.
"""


class _LoggerDbStub:
    """Returns empty data for every logger-database query."""

    def latest_global_events(self, limit=100):
        # TODO(webui): re-point at new Logger schema
        return []

    def count_events(self, guild_id, search=None, category=None):
        # TODO(webui): re-point at new Logger schema
        return 0

    def search_events(self, guild_id, search=None, category=None,
                      limit=50, offset=0):
        # TODO(webui): re-point at new Logger schema
        return []

    def get_event(self, guild_id, event_id):
        # TODO(webui): re-point at new Logger schema
        return None

    def get_log_channel(self, guild_id, log_type):
        # TODO(webui): re-point at new Logger schema
        return None

    def set_log_channel(self, guild_id, log_type, channel_id):
        # TODO(webui): re-point at new Logger schema
        return None

    def save_event_from_bot(self, guild_id=None, category=None,
                            action=None, payload=None):
        # TODO(webui): re-point at new Logger schema
        return None


logger_db = _LoggerDbStub()
