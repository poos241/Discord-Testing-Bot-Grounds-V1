"""Event history for the web dashboard, backed by the Logger's database.

The Logger cog records every logged event to the ``events`` table in
``data/message_log.db`` (see ``cogs/Logger/database.py``). This module
exposes the query interface the blueprints expect.
"""

import time
from datetime import datetime, timedelta, timezone


def _db():
    from cogs.Logger.database import db
    return db


def _date_bounds(date_from, date_to):
    """Logger page dates (YYYY-MM-DD) -> (start, end-exclusive) epoch UTC.

    Unparseable values are ignored (None) rather than erroring the page.
    """
    start = end = None
    if date_from:
        try:
            start = datetime.strptime(
                str(date_from).strip(), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc).timestamp()
        except ValueError:
            start = None
    if date_to:
        try:
            end = (datetime.strptime(
                str(date_to).strip(), "%Y-%m-%d").replace(
                    tzinfo=timezone.utc) + timedelta(days=1)).timestamp()
        except ValueError:
            end = None
    return start, end


def _normalize(event):
    """Add the fields the Logger history page already expects.

    Raw rows carry ``created_at`` (epoch) and ``summary`` (text); the
    page reads ``timestamp`` and ``data.description``. Raw keys are kept
    so existing consumers keep working.
    """
    if event is None:
        return None
    row = dict(event)
    created = row.get("created_at")
    try:
        row["timestamp"] = (
            datetime.fromtimestamp(float(created), tz=timezone.utc).isoformat()
            if created is not None else None
        )
    except (TypeError, ValueError):
        row["timestamp"] = None
    row["data"] = {"description": row.get("summary")}
    return row


def _filter_kwargs(filters):
    date_from, date_to = _date_bounds(
        filters.get("date_from"), filters.get("date_to"))
    return {
        "category": filters.get("category"),
        "event_type": filters.get("event_type"),
        "search": filters.get("search"),
        "user_id": filters.get("user_id"),
        "channel_id": filters.get("channel_id"),
        "date_from": date_from,
        "date_to": date_to,
    }


def publish_event(**kwargs):
    """Compat shim for the old ``core.event_publisher.publish_event``.

    The new Logger records events itself in ``Logger.send``; this is a
    no-op kept so old call sites don't break.
    """
    return {"stub": True, "note": "events are recorded by the Logger cog"}


class _EventStore:
    """Queryable event history for the web dashboard."""

    def _rows(self, guild_id, limit=5000):
        return _db().query_events(guild_id, limit=limit)

    # ----- counts -----
    def count(self):
        return 0

    def count_for_guild(self, guild_id):
        return _db().count_events(guild_id)

    def count_types_for_guild(self, guild_id):
        out = {}
        for e in self._rows(guild_id):
            if e["event_type"]:
                out[e["event_type"]] = out.get(e["event_type"], 0) + 1
        return out

    # ----- lists -----
    def latest(self, limit=100):
        return []

    def for_guild(self, guild_id, limit=100):
        return [_normalize(e) for e in _db().query_events(guild_id, limit=limit)]

    def all_for_guild(self, guild_id):
        return [_normalize(e) for e in _db().query_events(guild_id, limit=5000)]

    def for_user(self, guild_id, user_id, limit=100):
        # The events table has no user column: match the ID in the
        # recorded summary text (see cogs/Logger/database.py).
        return [_normalize(e) for e in _db().query_events(
            guild_id, user_id=user_id, limit=limit)]

    def for_channel(self, guild_id, channel_id, limit=100):
        # Same summary-text match as for_user.
        return [_normalize(e) for e in _db().query_events(
            guild_id, channel_id=channel_id, limit=limit)]

    def by_type(self, guild_id, event_type, limit=100):
        return [_normalize(e) for e in _db().query_events(
            guild_id, event_type=event_type, limit=limit)]

    def by_category(self, guild_id, category, limit=100):
        return [_normalize(e) for e in _db().query_events(
            guild_id, category=category, limit=limit)]

    def query(self, guild_id, limit=100, **filters):
        return [_normalize(e) for e in _db().query_events(
            guild_id,
            category=filters.get("category"),
            event_type=filters.get("event_type"),
            search=filters.get("search"),
            limit=limit,
        )]

    # ----- logger blueprint -----
    def guild_breakdown(self, guild_id):
        cats, types = {}, {}
        for e in self._rows(guild_id):
            cats[e["category"]] = cats.get(e["category"], 0) + 1
            if e["event_type"]:
                types[e["event_type"]] = types.get(e["event_type"], 0) + 1
        return {"categories": cats, "event_types": types}

    def guild_event_options(self, guild_id):
        rows = self._rows(guild_id)
        return {
            "categories": sorted({e["category"] for e in rows if e["category"]}),
            "event_types": sorted({e["event_type"] for e in rows if e["event_type"]}),
        }

    def guild_trend(self, guild_id, hours=24):
        cutoff = time.time() - hours * 3600
        buckets = {}
        for e in self._rows(guild_id):
            ts = e["created_at"] or 0
            if ts < cutoff:
                continue
            b = int(ts // 3600) * 3600
            buckets[b] = buckets.get(b, 0) + 1
        return [{"timestamp": b, "count": n} for b, n in sorted(buckets.items())]

    def guild_category_trend(self, guild_id, hours=24):
        cutoff = time.time() - hours * 3600
        buckets = {}
        for e in self._rows(guild_id):
            ts = e["created_at"] or 0
            if ts < cutoff:
                continue
            key = (int(ts // 3600) * 3600, e["category"])
            buckets[key] = buckets.get(key, 0) + 1
        return [{"t": b, "category": c, "n": n}
                for (b, c), n in sorted(buckets.items())]

    def query_page(self, page=1, per_page=50, guild_id=None, **filters):
        kwargs = _filter_kwargs(filters)
        events = _db().query_events(
            guild_id, limit=per_page, offset=(page - 1) * per_page, **kwargs)
        total = _db().count_events(guild_id, **kwargs)
        return {"events": [_normalize(e) for e in events], "page": page,
                "per_page": per_page, "total": total}

    def get(self, guild_id, event_id):
        for e in self._rows(guild_id):
            if e["id"] == event_id:
                return _normalize(e)
        return None

    def export_guild(self, guild_id, **filters):
        """All matching events (retention cap: 5000 per guild)."""
        return [_normalize(e) for e in _db().query_events(
            guild_id, limit=5000, **_filter_kwargs(filters))]


event_store = _EventStore()
