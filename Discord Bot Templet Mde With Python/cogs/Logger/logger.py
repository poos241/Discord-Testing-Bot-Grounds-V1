"""Sends log embeds to the configured per-guild, per-category channels."""
import discord

from .database import db


def _rich_summary(embed):
    """Flatten an embed into the searchable text recorded for the event.

    Logger embeds carry the who/where in fields and the author line,
    not in ``description`` -- recording only the description left the
    event history (and CSV export) with NULL summaries and no way to
    filter by user or channel. Field values contain the raw IDs
    (``User: name (`123...`)``, ``<#123...>`` mentions, author lines
    like ``name (123...)``), so this flattened text is what the
    per-user / per-channel export filters match against. Capped so one
    chatty event can't bloat the history table.
    """
    parts = []
    description = getattr(embed, "description", None)
    if description:
        parts.append(str(description))
    author = getattr(embed, "author", None)
    author_name = getattr(author, "name", None) if author else None
    if author_name:
        parts.append(f"Author: {author_name}")
    for field in getattr(embed, "fields", None) or []:
        name = getattr(field, "name", None)
        value = getattr(field, "value", None)
        if name and value:
            parts.append(f"{name}: {value}")
    text = "\n".join(parts)
    if len(text) > 2000:
        text = text[:1997] + "..."
    return text or None


class Logger:
    def __init__(self, bot):
        self.bot = bot

    async def send(self, guild, category, embed):
        """Send an embed to the guild's log channel for a category.

        Silently skips when no channel is configured, the channel is gone,
        or the bot can't send there. Every event is also recorded to the
        queryable event history used by the web dashboard.
        """
        try:
            db.record_event(
                guild.id,
                category,
                event_type=getattr(embed, "title", None),
                summary=_rich_summary(embed),
            )
        except Exception:
            pass
        channel_id = db.get_log_channel(guild.id, category)
        if not channel_id:
            return
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        try:
            await channel.send(embed=embed)
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass
