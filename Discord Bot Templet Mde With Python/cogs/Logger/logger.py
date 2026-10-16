"""Sends log embeds to the configured per-guild, per-category channels."""
import discord

from .database import db


class Logger:
    def __init__(self, bot):
        self.bot = bot

    async def send(self, guild, category, embed):
        """Send an embed to the guild's log channel for a category.

        Silently skips when no channel is configured, the channel is gone,
        or the bot can't send there.
        """
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
