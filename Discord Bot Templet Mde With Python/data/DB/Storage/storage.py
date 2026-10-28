from data.DB.db import database
from data.DB.models import welcome_data, main_vc_map, xp_timestamps, threads_settings, levels, ticket_config, active_tickets, ticket_records, profiles, profile_activity, qotd_questions, qotd_config, qotd_history, qotd_guild_exclusions, ticket_guild_config, support_tickets, appeal_guild_config, appeals, friendships, friend_settings, voice_xp_config, voice_xp_users, lockdown_channels, automod_config, auto_thread_channels, custom_badges, custom_badge_awards
from datetime import datetime
import time

async def get_welcome(guild_id: str):
    row = await database.fetch_one(welcome_data.select().where(welcome_data.c.guild_id == guild_id))
    return dict(row) if row else {}

async def save_welcome(guild_id: str, payload: dict):
    await database.execute(
        welcome_data.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_mainvc(guild_id: str):
    row = await database.fetch_one(main_vc_map.select().where(main_vc_map.c.guild_id == guild_id))
    return dict(row) if row else {}

async def save_mainvc(guild_id: str, payload: dict):
    await database.execute(
        main_vc_map.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_xp(guild_id: str):
    row = await database.fetch_one(xp_timestamps.select().where(xp_timestamps.c.guild_id == guild_id))
    return row["data"] if row else {}

async def save_xp(guild_id: str, data: dict):
    await database.execute(
        xp_timestamps.insert()
        .values(guild_id=guild_id, data=data)
        .prefix_with("OR REPLACE")
    )

async def get_threads_settings(guild_id: str):
    """
    Fetches the thread settings for a specific guild.
    Ensures correct column usage and avoids SQL injection/misinterpretation.
    """
    # Cast to string just to be safe — even if already str
    guild_id_str = str(guild_id)

    # Construct safe query
    query = threads_settings.select().where(threads_settings.c.guild_id == guild_id_str)

    # Fetch one row
    row = await database.fetch_one(query)
    return row

async def save_threads_settings(guild_id: str, payload: dict):
    await database.execute(
        threads_settings.insert()
        .values(guild_id=guild_id, **payload)
        .prefix_with("OR REPLACE")
    )

async def get_levels(guild_id: str):
    row = await database.fetch_one(levels.select().where(levels.c.guild_id == guild_id))
    return row["data"] if row else {}

async def save_levels(guild_id: str, data: dict):
    from discord.utils import get  # just in case you use it
    guild_name = data.get("settings", {}).get("guild_name", "Unknown")
    query = levels.insert().values(
        guild_id=guild_id,
        guild_name=guild_name,
        data=data
    ).prefix_with("OR REPLACE")
    await database.execute(query)
    
    
    
    
    
    
async def get_ticket_config(gid: str):
    row = await database.fetch_one(ticket_config.select().where(ticket_config.c.guild_id == str(gid)))
    return row["config"] if row else {}

async def save_ticket_config(gid: str, config: dict):
    await database.execute(
        ticket_config.insert().values(
            guild_id=str(gid),
            guild_name=config.get("guild_name", ""),
            config=config
        ).prefix_with("OR REPLACE")
    )

async def get_active_tickets(gid: str):
    row = await database.fetch_one(active_tickets.select().where(active_tickets.c.guild_id == str(gid)))
    return row["active"] if row else {}

async def save_active_tickets(gid: str, active: dict):
    await database.execute(
        active_tickets.insert().values(
            guild_id=str(gid),
            guild_name=active.get("guild_name", ""),
            active=active
        ).prefix_with("OR REPLACE")
    )

async def get_ticket_records(gid: str):
    row = await database.fetch_one(ticket_records.select().where(ticket_records.c.guild_id == str(gid)))
    return row["records"] if row else {}

async def save_ticket_records(gid: str, records: dict):
    await database.execute(
        ticket_records.insert().values(
            guild_id=str(gid),
            records=records
        ).prefix_with("OR REPLACE")
    )
    
    
    


async def get_profile(user_id: str):
    row = await database.fetch_one(profiles.select().where(profiles.c.user_id == str(user_id)))
    return dict(row) if row else {}


async def save_profile(user_id: str, data: dict):
    await database.execute(
        profiles.insert()
        .values(user_id=str(user_id), **data)
        .prefix_with("OR REPLACE")
    )


async def list_public_profiles():
    rows = await database.fetch_all(
        profiles.select().where(profiles.c.public == True)
    )
    return [dict(r) for r in rows]


async def log_activity(user_id, guild_id, kind, detail):
    """Append one activity-feed event. Never raises to callers."""
    try:
        await database.execute(
            profile_activity.insert().values(
                user_id=str(user_id),
                guild_id=str(guild_id),
                kind=kind,
                detail=detail or {},
                ts=int(time.time()),
            )
        )
    except Exception:
        pass


async def get_activity(user_id: str, limit: int = 20):
    rows = await database.fetch_all(
        profile_activity.select()
        .where(profile_activity.c.user_id == str(user_id))
        .order_by(profile_activity.c.id.desc())
        .limit(limit)
    )
    return [dict(r) for r in rows]

async def list_public_activity(limit: int = 30, offset: int = 0, kind: str = None):
    """Global activity rows, restricted to public profiles only.

    Same privacy rule as list_public_profiles / the member
    directory: activity from a user whose profile is not public
    never appears here. Callers must still strip guild_id
    before responding -- it is in the row but is never part
    of the feed output, so the feed cannot reveal which
    servers a person is in.
    """
    public_rows = await list_public_profiles()
    user_ids = [
        str(r.get("user_id"))
        for r in public_rows
        if r.get("user_id")
    ]
    if not user_ids:
        return []
    query = profile_activity.select().where(
        profile_activity.c.user_id.in_(user_ids)
    )
    if kind:
        query = query.where(profile_activity.c.kind == kind)
    query = (
        query.order_by(profile_activity.c.id.desc())
        .limit(limit)
        .offset(offset)
    )
    rows = await database.fetch_all(query)
    return [dict(r) for r in rows]


# ---------------- Question of the Day (QOTD) ----------------
# Questions live in one global pool; config/history/exclusions are
# per-guild. Selection logic (no repeats until exhausted) lives in
# the QOTD cog; these helpers are plain table access.

async def get_qotd_config(guild_id: str):
    row = await database.fetch_one(qotd_config.select().where(qotd_config.c.guild_id == str(guild_id)))
    return dict(row) if row else {}


async def save_qotd_config(guild_id: str, payload: dict):
    await database.execute(
        qotd_config.insert()
        .values(guild_id=str(guild_id), **payload)
        .prefix_with("OR REPLACE")
    )


async def list_qotd_configs():
    rows = await database.fetch_all(qotd_config.select())
    return [dict(r) for r in rows]


async def list_qotd_questions(status: str = None):
    query = qotd_questions.select()
    if status is not None:
        query = query.where(qotd_questions.c.status == status)
    rows = await database.fetch_all(query.order_by(qotd_questions.c.id.asc()))
    return [dict(r) for r in rows]


async def get_qotd_question(qid: int):
    row = await database.fetch_one(qotd_questions.select().where(qotd_questions.c.id == int(qid)))
    return dict(row) if row else {}


async def add_qotd_question(text: str, source: str, submitter_id: str = "", submitted_guild_id: str = "", status: str = "approved"):
    qid = await database.execute(
        qotd_questions.insert().values(
            text=text, status=status, active=True, source=source,
            submitter_id=str(submitter_id or ""), submitted_guild_id=str(submitted_guild_id or ""),
        )
    )
    return qid


async def set_qotd_question(qid: int, **fields):
    await database.execute(
        qotd_questions.update().where(qotd_questions.c.id == int(qid)).values(**fields)
    )


async def count_qotd_by_source(source: str):
    rows = await database.fetch_all(qotd_questions.select().where(qotd_questions.c.source == source))
    return len(rows)


async def add_qotd_exclusion(guild_id: str, qid: int):
    await database.execute(
        qotd_guild_exclusions.insert().values(guild_id=str(guild_id), question_id=int(qid)).prefix_with("OR IGNORE")
    )


async def list_qotd_exclusions(guild_id: str):
    rows = await database.fetch_all(
        qotd_guild_exclusions.select().where(qotd_guild_exclusions.c.guild_id == str(guild_id))
    )
    return [r["question_id"] for r in rows]


async def list_qotd_posted_ids(guild_id: str):
    rows = await database.fetch_all(
        qotd_history.select().where(qotd_history.c.guild_id == str(guild_id))
    )
    return [r["question_id"] for r in rows]


async def get_qotd_post_for_date(guild_id: str, date_str: str):
    """Latest history row for a guild on a date (a skipped row replaced
    by a new post leaves the new row latest)."""
    rows = await database.fetch_all(
        qotd_history.select()
        .where(qotd_history.c.guild_id == str(guild_id))
        .where(qotd_history.c.posted_date == date_str)
        .order_by(qotd_history.c.id.desc())
        .limit(1)
    )
    return dict(rows[0]) if rows else {}


async def add_qotd_history(guild_id: str, question_id: int, posted_date: str, message_id: str = "", thread_id: str = ""):
    await database.execute(
        qotd_history.insert().values(
            guild_id=str(guild_id), question_id=int(question_id), posted_date=posted_date,
            message_id=str(message_id or ""), thread_id=str(thread_id or ""), skipped=False,
        )
    )


async def mark_qotd_history_skipped(history_id: int):
    await database.execute(
        qotd_history.update().where(qotd_history.c.id == int(history_id)).values(skipped=True)
    )


async def get_qotd_history(guild_id: str, limit: int = 25):
    """Newest-first history rows with their question text attached."""
    rows = await database.fetch_all(
        qotd_history.select()
        .where(qotd_history.c.guild_id == str(guild_id))
        .order_by(qotd_history.c.id.desc())
        .limit(limit)
    )
    out = []
    for r in rows:
        row = dict(r)
        q = await get_qotd_question(row["question_id"])
        row["text"] = q.get("text", "") if q else ""
        out.append(row)
    return out


# Support tickets (built new 2026-10-27; see cogs/Tickets.py).
# NOTE on save_ticket_guild_config: it MERGES with the existing row
# before writing. A plain INSERT OR REPLACE with a partial payload
# would silently reset every other setting (including next_number)
# to its default, so partial updates must never go straight to the
# table. This helper is the only writer for ticket_guild_config.

_TICKET_CONFIG_COLUMNS = (
    "staff_role_id", "category_id", "log_channel_id",
    "panel_channel_id", "panel_message_id", "next_number", "enabled",
)


async def get_ticket_guild_config(guild_id: str):
    row = await database.fetch_one(
        ticket_guild_config.select().where(
            ticket_guild_config.c.guild_id == str(guild_id)))
    return dict(row) if row else {}


async def save_ticket_guild_config(guild_id: str, payload: dict):
    current = await get_ticket_guild_config(guild_id)
    merged = {k: current.get(k) for k in _TICKET_CONFIG_COLUMNS}
    merged.update({k: v for k, v in payload.items()
                   if k in _TICKET_CONFIG_COLUMNS})
    values = {k: v for k, v in merged.items() if v is not None}
    values.setdefault("next_number", 1)
    values.setdefault("enabled", True)
    await database.execute(
        ticket_guild_config.insert()
        .values(guild_id=str(guild_id), **values)
        .prefix_with("OR REPLACE")
    )


async def create_support_ticket(guild_id, number, user_id, channel_id, topic):
    row_id = await database.execute(
        support_tickets.insert().values(
            guild_id=str(guild_id), number=int(number),
            user_id=str(user_id), channel_id=str(channel_id),
            topic=topic, status="open",
        )
    )
    return {
        "id": row_id, "guild_id": str(guild_id), "number": int(number),
        "user_id": str(user_id), "channel_id": str(channel_id),
        "topic": topic, "status": "open",
    }


async def get_ticket_by_channel(guild_id: str, channel_id: str):
    row = await database.fetch_one(
        support_tickets.select().where(
            (support_tickets.c.guild_id == str(guild_id))
            & (support_tickets.c.channel_id == str(channel_id)))
        .order_by(support_tickets.c.id.desc()))
    return dict(row) if row else None


async def get_open_ticket_for_user(guild_id: str, user_id: str):
    row = await database.fetch_one(
        support_tickets.select().where(
            (support_tickets.c.guild_id == str(guild_id))
            & (support_tickets.c.user_id == str(user_id))
            & (support_tickets.c.status == "open"))
        .order_by(support_tickets.c.id.desc()))
    return dict(row) if row else None


async def list_open_tickets(guild_id: str):
    rows = await database.fetch_all(
        support_tickets.select().where(
            (support_tickets.c.guild_id == str(guild_id))
            & (support_tickets.c.status == "open"))
        .order_by(support_tickets.c.number.asc()))
    return [dict(r) for r in rows]


async def update_support_ticket(ticket_id: int, payload: dict):
    values = dict(payload)
    if values.get("status") == "closed" and "closed_at" not in values:
        values["closed_at"] = datetime.now()
    if values.get("status") == "open":
        values["closed_at"] = None
    await database.execute(
        support_tickets.update()
        .where(support_tickets.c.id == int(ticket_id))
        .values(**values)
    )


# Ban/timeout appeals (built 2026-10-27; see cogs/Appeals.py).
# Same merge rule as save_ticket_guild_config: a plain INSERT OR
# REPLACE with a partial payload would silently reset the other
# settings, so partial updates merge with the existing row first.

_APPEAL_CONFIG_COLUMNS = (
    "appeals_channel_id", "staff_role_id", "enabled",
)


async def get_appeal_guild_config(guild_id: str):
    row = await database.fetch_one(
        appeal_guild_config.select().where(
            appeal_guild_config.c.guild_id == str(guild_id)))
    return dict(row) if row else {}


async def save_appeal_guild_config(guild_id: str, payload: dict):
    current = await get_appeal_guild_config(guild_id)
    merged = {k: current.get(k) for k in _APPEAL_CONFIG_COLUMNS}
    merged.update({k: v for k, v in payload.items()
                   if k in _APPEAL_CONFIG_COLUMNS})
    values = {k: v for k, v in merged.items() if v is not None}
    values.setdefault("enabled", True)
    await database.execute(
        appeal_guild_config.insert()
        .values(guild_id=str(guild_id), **values)
        .prefix_with("OR REPLACE")
    )


async def create_appeal(guild_id, user_id, user_name, appeal_type, text):
    row_id = await database.execute(
        appeals.insert().values(
            guild_id=str(guild_id), user_id=str(user_id),
            user_name=user_name, appeal_type=appeal_type,
            text=text, status="pending",
        )
    )
    return {
        "id": row_id, "guild_id": str(guild_id), "user_id": str(user_id),
        "user_name": user_name, "appeal_type": appeal_type,
        "text": text, "status": "pending",
    }


async def get_appeal(appeal_id: int):
    row = await database.fetch_one(
        appeals.select().where(appeals.c.id == int(appeal_id)))
    return dict(row) if row else None


async def get_pending_appeal_for_user(guild_id: str, user_id: str):
    """The user's open appeal in this guild, if any (one pending
    appeal per user per guild is enforced by the cog)."""
    row = await database.fetch_one(
        appeals.select().where(
            (appeals.c.guild_id == str(guild_id))
            & (appeals.c.user_id == str(user_id))
            & (appeals.c.status == "pending"))
        .order_by(appeals.c.id.desc()))
    return dict(row) if row else None


async def list_appeals(guild_id: str, status=None):
    query = appeals.select().where(appeals.c.guild_id == str(guild_id))
    if status is not None:
        query = query.where(appeals.c.status == status)
    rows = await database.fetch_all(query.order_by(appeals.c.id.asc()))
    return [dict(r) for r in rows]


async def update_appeal(appeal_id: int, payload: dict):
    values = dict(payload)
    if values.get("status") in ("approved", "denied") and "decided_at" not in values:
        values["decided_at"] = datetime.now()
    await database.execute(
        appeals.update()
        .where(appeals.c.id == int(appeal_id))
        .values(**values)
    )


# Website friend system (built 2026-10-28; see web/blueprints/friends.py).
# One row per pair of users, in either direction. Pair lookups use
# sqlalchemy.or_ so a request in either direction is found.

import sqlalchemy as _sa


async def get_friend_settings(user_id: str):
    row = await database.fetch_one(friend_settings.select().where(friend_settings.c.user_id == str(user_id)))
    return dict(row) if row else {}


async def save_friend_settings(user_id: str, allow_requests: bool):
    await database.execute(
        friend_settings.insert()
        .values(user_id=str(user_id), allow_requests=bool(allow_requests))
        .prefix_with("OR REPLACE")
    )


async def get_friend_pair(user_a: str, user_b: str):
    """The friendships row for a pair, in either direction, if any."""
    row = await database.fetch_one(
        friendships.select().where(
            _sa.or_(
                (friendships.c.requester_id == str(user_a)) & (friendships.c.addressee_id == str(user_b)),
                (friendships.c.requester_id == str(user_b)) & (friendships.c.addressee_id == str(user_a)),
            )
        ).order_by(friendships.c.id.desc()))
    return dict(row) if row else None


async def get_friend_request(request_id: int):
    row = await database.fetch_one(friendships.select().where(friendships.c.id == int(request_id)))
    return dict(row) if row else None


async def create_or_reopen_friend_request(requester_id: str, addressee_id: str, requester_name: str, created_ts: int):
    """Insert a pending request, or flip an old declined row for the
    pair back to pending with the new direction. Callers check for an
    existing pending/accepted row first, so this never overwrites one."""
    existing = await get_friend_pair(requester_id, addressee_id)
    if existing and existing.get("status") == "declined":
        await database.execute(
            friendships.update().where(friendships.c.id == existing["id"]).values(
                requester_id=str(requester_id),
                addressee_id=str(addressee_id),
                status="pending",
                requester_name=requester_name or "",
                created_ts=int(created_ts),
                decided_ts=None,
            )
        )
        return dict(existing, requester_id=str(requester_id), addressee_id=str(addressee_id), status="pending")
    row_id = await database.execute(
        friendships.insert().values(
            requester_id=str(requester_id),
            addressee_id=str(addressee_id),
            status="pending",
            requester_name=requester_name or "",
            created_ts=int(created_ts),
            decided_ts=None,
        )
    )
    return {"id": row_id, "requester_id": str(requester_id), "addressee_id": str(addressee_id), "status": "pending"}


async def update_friend_request(request_id: int, status: str, decided_ts: int):
    await database.execute(
        friendships.update().where(friendships.c.id == int(request_id)).values(
            status=status, decided_ts=int(decided_ts))
    )


async def delete_friend_request(request_id: int):
    await database.execute(
        friendships.delete().where(friendships.c.id == int(request_id))
    )


async def list_accepted_friends(user_id: str):
    rows = await database.fetch_all(
        friendships.select().where(
            _sa.or_(
                friendships.c.requester_id == str(user_id),
                friendships.c.addressee_id == str(user_id),
            ) & (friendships.c.status == "accepted")
        ).order_by(friendships.c.decided_ts.desc()))
    return [dict(r) for r in rows]


async def list_incoming_pending_friends(user_id: str):
    rows = await database.fetch_all(
        friendships.select().where(
            (friendships.c.addressee_id == str(user_id))
            & (friendships.c.status == "pending")
        ).order_by(friendships.c.created_ts.desc()))
    return [dict(r) for r in rows]


async def list_outgoing_pending_friends(user_id: str):
    rows = await database.fetch_all(
        friendships.select().where(
            (friendships.c.requester_id == str(user_id))
            & (friendships.c.status == "pending")
        ).order_by(friendships.c.created_ts.desc()))
    return [dict(r) for r in rows]


async def decline_pending_for_user(user_id: str, decided_ts: int):
    """Auto-decline every pending incoming request for a user (used
    when the opt-out toggle is turned on). Returns how many."""
    rows = await list_incoming_pending_friends(user_id)
    for row in rows:
        await update_friend_request(row["id"], "declined", decided_ts)
    return len(rows)


# Voice time XP + VC leaderboard (built 2026-10-28; see cogs/VoiceXP.py).
# Config saves MERGE with the existing row (same rule as tickets /
# appeals): a plain INSERT OR REPLACE with a partial payload would
# silently reset the other settings. User rows are always written
# whole by the cog, so save_voice_xp_user is a straight upsert.

_VOICE_XP_CONFIG_COLUMNS = (
    "xp_per_minute", "daily_cap_xp", "enabled",
)

_VOICE_XP_USER_COLUMNS = (
    "opted_in", "display_name", "total_minutes",
    "total_voice_xp", "xp_today", "xp_day",
)


async def get_voice_xp_config(guild_id: str):
    row = await database.fetch_one(
        voice_xp_config.select().where(
            voice_xp_config.c.guild_id == str(guild_id)))
    return dict(row) if row else {}


async def save_voice_xp_config(guild_id: str, payload: dict):
    current = await get_voice_xp_config(guild_id)
    merged = {k: current.get(k) for k in _VOICE_XP_CONFIG_COLUMNS}
    merged.update({k: v for k, v in payload.items()
                   if k in _VOICE_XP_CONFIG_COLUMNS})
    values = {k: v for k, v in merged.items() if v is not None}
    values.setdefault("xp_per_minute", 1)
    values.setdefault("daily_cap_xp", 100)
    values.setdefault("enabled", True)
    await database.execute(
        voice_xp_config.insert()
        .values(guild_id=str(guild_id), **values)
        .prefix_with("OR REPLACE")
    )


async def get_voice_xp_user(guild_id: str, user_id: str):
    row = await database.fetch_one(
        voice_xp_users.select().where(
            (voice_xp_users.c.guild_id == str(guild_id))
            & (voice_xp_users.c.user_id == str(user_id))))
    return dict(row) if row else {}


async def save_voice_xp_user(guild_id: str, user_id: str, payload: dict):
    values = {k: payload.get(k) for k in _VOICE_XP_USER_COLUMNS}
    values.setdefault("opted_in", False)
    values.setdefault("display_name", "")
    values.setdefault("total_minutes", 0)
    values.setdefault("total_voice_xp", 0)
    values.setdefault("xp_today", 0)
    values.setdefault("xp_day", "")
    await database.execute(
        voice_xp_users.insert()
        .values(guild_id=str(guild_id), user_id=str(user_id), **values)
        .prefix_with("OR REPLACE")
    )


async def list_voice_xp_users(guild_id: str):
    rows = await database.fetch_all(
        voice_xp_users.select().where(
            voice_xp_users.c.guild_id == str(guild_id)))
    return [dict(r) for r in rows]


async def list_voice_xp_top(guild_id: str, limit: int = 10):
    """Top members by banked voice minutes (opted-out members keep
    their banked totals, so they still appear here)."""
    rows = await database.fetch_all(
        voice_xp_users.select().where(
            voice_xp_users.c.guild_id == str(guild_id))
        .order_by(voice_xp_users.c.total_minutes.desc())
        .limit(int(limit)))
    return [dict(r) for r in rows]


# Lockdown + slowmode (built 2026-10-28; see cogs/Lockdown.py).
# Rows are always written whole by the cog, so save_lockdown is a
# straight upsert, same rule as the voice XP user rows.

_LOCKDOWN_COLUMNS = (
    "previous_send_messages", "locked_by", "locked_at",
    "unlock_at", "reason", "scope",
)


async def get_lockdown(guild_id: str, channel_id: str):
    row = await database.fetch_one(
        lockdown_channels.select().where(
            (lockdown_channels.c.guild_id == str(guild_id))
            & (lockdown_channels.c.channel_id == str(channel_id))))
    return dict(row) if row else {}


async def save_lockdown(guild_id: str, channel_id: str, payload: dict):
    values = {k: payload.get(k) for k in _LOCKDOWN_COLUMNS}
    values.setdefault("previous_send_messages", -1)
    values.setdefault("locked_by", "")
    values.setdefault("locked_at", 0)
    values.setdefault("reason", "")
    values.setdefault("scope", "channel")
    await database.execute(
        lockdown_channels.insert()
        .values(guild_id=str(guild_id), channel_id=str(channel_id), **values)
        .prefix_with("OR REPLACE")
    )


async def delete_lockdown(guild_id: str, channel_id: str):
    await database.execute(
        lockdown_channels.delete().where(
            (lockdown_channels.c.guild_id == str(guild_id))
            & (lockdown_channels.c.channel_id == str(channel_id))))


async def list_lockdowns(guild_id: str):
    rows = await database.fetch_all(
        lockdown_channels.select().where(
            lockdown_channels.c.guild_id == str(guild_id)))
    return [dict(r) for r in rows]


async def list_due_lockdowns(now_ts: int):
    """Rows whose timed lock has expired (unlock_at set and reached)."""
    rows = await database.fetch_all(
        lockdown_channels.select().where(
            (lockdown_channels.c.unlock_at.isnot(None))
            & (lockdown_channels.c.unlock_at <= int(now_ts))))
    return [dict(r) for r in rows]

# Automod basics (built 2026-10-28; see cogs/Automod.py). Config saves
# MERGE with the existing row (same rule as tickets / appeals /
# voice XP): a plain INSERT OR REPLACE with a partial payload would
# silently reset every other rule to OFF, so partial updates must
# never go straight to the table. get_automod_config always returns
# a full dict with defaults filled in, so a guild with no row yet
# reads as "everything off, 5 messages in 10 seconds".

_AUTOMOD_DEFAULTS = {
    "spam_enabled": False,
    "invites_enabled": False,
    "external_links_enabled": False,
    "caps_enabled": False,
    "spam_threshold": 5,
    "spam_window_seconds": 10,
}


async def get_automod_config(guild_id: str):
    row = await database.fetch_one(
        automod_config.select().where(
            automod_config.c.guild_id == str(guild_id)))
    cfg = dict(_AUTOMOD_DEFAULTS)
    if row:
        for key in _AUTOMOD_DEFAULTS:
            if row[key] is not None:
                cfg[key] = row[key]
    return cfg


async def save_automod_config(guild_id: str, payload: dict):
    current = await get_automod_config(guild_id)
    current.update({k: v for k, v in payload.items()
                    if k in _AUTOMOD_DEFAULTS})
    await database.execute(
        automod_config.insert()
        .values(guild_id=str(guild_id), **current)
        .prefix_with("OR REPLACE")
    )

# Auto-threads (built 2026-10-28; see cogs/AutoThreads.py). One row
# per designated channel; saves are whole-row upserts, same rule as
# the lockdown rows, so a partial update can never reset the other
# setting. get_auto_thread_channel returns {} for a channel that
# is not designated, which is how the listener tells designated
# channels from ordinary ones.

_AUTO_THREAD_COLUMNS = ("archive_minutes", "name_prefix")


async def get_auto_thread_channel(guild_id: str, channel_id: str):
    row = await database.fetch_one(
        auto_thread_channels.select().where(
            (auto_thread_channels.c.guild_id == str(guild_id))
            & (auto_thread_channels.c.channel_id == str(channel_id))))
    return dict(row) if row else {}


async def save_auto_thread_channel(guild_id: str, channel_id: str, payload: dict):
    values = {k: payload.get(k) for k in _AUTO_THREAD_COLUMNS}
    values.setdefault("archive_minutes", 1440)
    values.setdefault("name_prefix", "")
    await database.execute(
        auto_thread_channels.insert()
        .values(guild_id=str(guild_id), channel_id=str(channel_id), **values)
        .prefix_with("OR REPLACE")
    )


async def delete_auto_thread_channel(guild_id: str, channel_id: str):
    await database.execute(
        auto_thread_channels.delete().where(
            (auto_thread_channels.c.guild_id == str(guild_id))
            & (auto_thread_channels.c.channel_id == str(channel_id))))


async def list_auto_thread_channels(guild_id: str):
    rows = await database.fetch_all(
        auto_thread_channels.select().where(
            auto_thread_channels.c.guild_id == str(guild_id)))
    return [dict(r) for r in rows]


# ---------------- Mod-awardable custom badges ----------------
# Badge definitions are per-guild (slug unique within a guild);
# awards link a badge to a member. These helpers are plain table
# access; the slug/name rules live in cogs/CustomBadges.py.
# list_custom_badge_awards_for_user returns only display fields --
# never guild ids -- so the web profile shelf (including public
# pages) cannot leak which server a badge came from.

async def create_custom_badge(guild_id, slug, name, icon, description, created_by):
    """Insert a badge definition; returns the row, or None if the
    slug is already taken in this guild."""
    existing = await database.fetch_one(
        custom_badges.select().where(
            (custom_badges.c.guild_id == str(guild_id))
            & (custom_badges.c.slug == slug)))
    if existing:
        return None
    badge_id = await database.execute(
        custom_badges.insert().values(
            guild_id=str(guild_id), slug=slug, name=name,
            icon=icon or "", description=description or "",
            created_by=str(created_by)))
    row = await database.fetch_one(
        custom_badges.select().where(custom_badges.c.id == badge_id))
    return dict(row) if row else {"id": badge_id, "slug": slug, "name": name}


async def get_custom_badge(guild_id, slug):
    """One badge definition by (guild, slug); {} when it is not found."""
    row = await database.fetch_one(
        custom_badges.select().where(
            (custom_badges.c.guild_id == str(guild_id))
            & (custom_badges.c.slug == slug)))
    return dict(row) if row else {}


async def get_custom_badge_by_name(guild_id, name):
    """One badge definition by (guild, name), case-insensitive;
    {} when it is not found. Used so /badge award accepts a badge
    name as well as its slug."""
    rows = await database.fetch_all(
        custom_badges.select().where(
            custom_badges.c.guild_id == str(guild_id)))
    for row in rows:
        if str(row["name"]).lower() == str(name).lower():
            return dict(row)
    return {}


async def list_custom_badges(guild_id):
    """All badge definitions for a guild, oldest first."""
    rows = await database.fetch_all(
        custom_badges.select().where(
            custom_badges.c.guild_id == str(guild_id))
        .order_by(custom_badges.c.id))
    return [dict(r) for r in rows]


async def delete_custom_badge(guild_id, slug):
    """Delete a badge definition and all its awards. Returns the
    number of awards removed, or None when the badge is not found."""
    badge = await get_custom_badge(guild_id, slug)
    if not badge:
        return None
    awards = await database.fetch_all(
        custom_badge_awards.select().where(
            custom_badge_awards.c.badge_id == badge["id"]))
    await database.execute(
        custom_badge_awards.delete().where(
            custom_badge_awards.c.badge_id == badge["id"]))
    await database.execute(
        custom_badges.delete().where(custom_badges.c.id == badge["id"]))
    return len(awards)


async def award_custom_badge(badge_id, guild_id, user_id, awarded_by):
    """Award a badge to a member. Returns True on a new award,
    False when the member already has it (or the badge id is not
    from this guild, so a stale id cannot award across servers)."""
    badge = await database.fetch_one(
        custom_badges.select().where(custom_badges.c.id == badge_id))
    if not badge or str(badge["guild_id"]) != str(guild_id):
        return False
    existing = await database.fetch_one(
        custom_badge_awards.select().where(
            (custom_badge_awards.c.badge_id == badge_id)
            & (custom_badge_awards.c.user_id == str(user_id))))
    if existing:
        return False
    await database.execute(
        custom_badge_awards.insert().values(
            badge_id=badge_id, guild_id=str(guild_id),
            user_id=str(user_id), awarded_by=str(awarded_by)))
    return True


async def remove_custom_badge_award(badge_id, user_id):
    """Revoke one member's award. Returns True when an award was
    removed, False when the member did not have the badge."""
    existing = await database.fetch_one(
        custom_badge_awards.select().where(
            (custom_badge_awards.c.badge_id == badge_id)
            & (custom_badge_awards.c.user_id == str(user_id))))
    if not existing:
        return False
    await database.execute(
        custom_badge_awards.delete().where(
            (custom_badge_awards.c.badge_id == badge_id)
            & (custom_badge_awards.c.user_id == str(user_id))))
    return True


async def count_custom_badge_awards(badge_id):
    """How many members hold this badge (for /badge list)."""
    rows = await database.fetch_all(
        custom_badge_awards.select().where(
            custom_badge_awards.c.badge_id == badge_id))
    return len(rows)


async def list_custom_badge_awards_for_user(user_id):
    """Every badge awarded to a user, across guilds, as display
    rows only (id, icon, name, description). Deliberately no guild
    id: the web profile shelf renders these on own AND public
    pages, and a public page must never reveal which servers a
    member is in."""
    awards = await database.fetch_all(
        custom_badge_awards.select().where(
            custom_badge_awards.c.user_id == str(user_id))
        .order_by(custom_badge_awards.c.awarded_at))
    out = []
    for award in awards:
        badge = await database.fetch_one(
            custom_badges.select().where(
                custom_badges.c.id == award["badge_id"]))
        if badge:
            out.append({
                "id": badge["id"],
                "icon": badge["icon"],
                "name": badge["name"],
                "description": badge["description"],
            })
    return out
