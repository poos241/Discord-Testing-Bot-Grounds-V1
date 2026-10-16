"""Logs message sends (cached), edits, and deletes."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import MESSAGE, COLORS
from .database import db
from .embeds import LoggerEmbed


class MessageLogger(BaseLogger):
    """Caches every guild message; logs edits and deletes."""

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        db.save_message(message)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild is None:
            return
        cached = db.get_message(message.id)
        content = message.content or (cached["content"] if cached else "")
        author_name = str(message.author) if message.author else (
            cached["author_name"] if cached else "Unknown"
        )

        embed = LoggerEmbed.base("🗑 Message Deleted", COLORS[MESSAGE])
        if message.author:
            LoggerEmbed.author(embed, message.author)
        else:
            embed.set_author(name=author_name)
        LoggerEmbed.field(embed, "Channel", message.channel.mention, inline=True)
        LoggerEmbed.field(embed, "Content", content or "*No message content.*")
        if message.created_at:
            LoggerEmbed.field(
                embed, "Sent",
                discord.utils.format_dt(message.created_at, style="F"),
            )
        attachments = message.attachments or []
        if attachments:
            lines = [f"📎 [{a.filename}]({a.url})" for a in attachments]
            LoggerEmbed.field(embed, "Attachments", "\n".join(lines))
            for a in attachments:
                if (a.content_type or "").startswith("image"):
                    embed.set_image(url=a.url)
                    break
        LoggerEmbed.finalize(embed)

        await self.send(message.guild, MESSAGE, embed)
        db.delete_message(message.id)

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or before.guild is None:
            return
        if before.content == after.content:
            return

        embed = LoggerEmbed.base("✏ Message Edited", COLORS[MESSAGE])
        LoggerEmbed.author(embed, before.author)
        LoggerEmbed.field(embed, "Channel", before.channel.mention, inline=True)
        LoggerEmbed.field(embed, "Before", before.content or "*Empty*")
        LoggerEmbed.field(embed, "After", after.content or "*Empty*")
        LoggerEmbed.field(embed, "Jump", f"[Go to message]({after.jump_url})")
        LoggerEmbed.finalize(embed)

        await self.send(before.guild, MESSAGE, embed)
        db.save_message(after)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        channel = guild.get_channel(payload.channel_id)
        embed = LoggerEmbed.base("🧹 Bulk Messages Deleted", COLORS[MESSAGE])
        LoggerEmbed.field(
            embed, "Channel",
            channel.mention if channel else f"<#{payload.channel_id}>",
            inline=True,
        )
        LoggerEmbed.field(embed, "Count", len(payload.message_ids), inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(guild, MESSAGE, embed)
