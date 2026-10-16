"""Logs channel and thread create/delete/update events."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import (SERVER, COLORS, EV_CHANNEL_CREATE, EV_CHANNEL_DELETE,
    EV_CHANNEL_UPDATE, EV_THREAD_CREATE, EV_THREAD_DELETE)
from .embeds import LoggerEmbed
from .database import db


class ChannelLogger(BaseLogger):
    # ----- channels -----

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not db.is_enabled(channel.guild.id, EV_CHANNEL_CREATE):
            return
        embed = LoggerEmbed.base("📁 Channel Created", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", f"#{channel.name}" if hasattr(channel, "name") else str(channel))
        LoggerEmbed.field(embed, "Type", str(channel.type), inline=True)
        category = getattr(channel, "category", None)
        LoggerEmbed.field(embed, "Category", category.name if category else "None", inline=True)
        entry = await self.audit_entry(
            channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id
        )
        if entry:
            LoggerEmbed.field(embed, "Created By", str(entry.user), inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(channel.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not db.is_enabled(channel.guild.id, EV_CHANNEL_DELETE):
            return
        embed = LoggerEmbed.base("🗑 Channel Deleted", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", getattr(channel, "name", str(channel)))
        category = getattr(channel, "category", None)
        LoggerEmbed.field(embed, "Category", category.name if category else "None", inline=True)
        entry = await self.audit_entry(
            channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id
        )
        if entry:
            LoggerEmbed.field(embed, "Deleted By", str(entry.user), inline=True)
            if entry.reason:
                LoggerEmbed.field(embed, "Reason", entry.reason)
        LoggerEmbed.finalize(embed)
        await self.send(channel.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_guild_channel_update(self, before, after):
        if before.name != after.name:
            await self._renamed(before, after)
        if isinstance(before, discord.TextChannel) and before.topic != after.topic:
            await self._topic(before, after)
        if getattr(before, "slowmode_delay", None) != getattr(after, "slowmode_delay", None):
            await self._slowmode(before, after)

    async def _renamed(self, before, after):
        if not db.is_enabled(after.guild.id, EV_CHANNEL_UPDATE):
            return
        embed = LoggerEmbed.base("✏ Channel Renamed", COLORS[SERVER])
        LoggerEmbed.field(embed, "Before", f"#{before.name}")
        LoggerEmbed.field(embed, "After", f"#{after.name}")
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    async def _topic(self, before, after):
        if not db.is_enabled(after.guild.id, EV_CHANNEL_UPDATE):
            return
        embed = LoggerEmbed.base("📝 Channel Topic Updated", COLORS[SERVER])
        LoggerEmbed.field(embed, "Channel", after.mention, inline=True)
        LoggerEmbed.field(embed, "Before", before.topic or "*None*")
        LoggerEmbed.field(embed, "After", after.topic or "*None*")
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    async def _slowmode(self, before, after):
        if not db.is_enabled(after.guild.id, EV_CHANNEL_UPDATE):
            return
        embed = LoggerEmbed.base("🐢 Slowmode Updated", COLORS[SERVER])
        LoggerEmbed.field(embed, "Channel", after.mention, inline=True)
        LoggerEmbed.field(embed, "Before", f"{before.slowmode_delay}s", inline=True)
        LoggerEmbed.field(embed, "After", f"{after.slowmode_delay}s", inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    # ----- threads -----

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not db.is_enabled(thread.guild.id, EV_THREAD_CREATE):
            return
        embed = LoggerEmbed.base("🧵 Thread Created", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", thread.name)
        LoggerEmbed.field(embed, "Channel", thread.parent.mention if thread.parent else "Unknown", inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(thread.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        if not db.is_enabled(thread.guild.id, EV_THREAD_DELETE):
            return
        embed = LoggerEmbed.base("🗑 Thread Deleted", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", thread.name)
        LoggerEmbed.finalize(embed)
        await self.send(thread.guild, SERVER, embed)
