"""Logs channel and thread create/delete/update events."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import (SERVER, EV_CHANNEL_CREATE, EV_CHANNEL_DELETE,
    EV_CHANNEL_UPDATE, EV_THREAD_CREATE, EV_THREAD_DELETE)
from .embeds import LoggerEmbed
from .database import db


class ChannelLogger(BaseLogger):
    # ----- channels -----

    @commands.Cog.listener()
    async def on_guild_channel_create(self, channel):
        if not db.is_enabled(channel.guild.id, EV_CHANNEL_CREATE):
            return
        entry = await self.audit_entry(
            channel.guild, discord.AuditLogAction.channel_create, target_id=channel.id
        )
        category = getattr(channel, "category", None)
        created_by = ""
        if entry:
            created_by = f"\n**Created By:** {entry.user}"
        embed = LoggerEmbed.base(
            "📁 Channel Created",
            LoggerEmbed.GREEN,
            description=(
                f"**Channel:** {channel.mention}\n"
                f"**Type:** {channel.type}\n"
                f"**Category:** {category.name if category else 'None'}"
                f"{created_by}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(channel.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_guild_channel_delete(self, channel):
        if not db.is_enabled(channel.guild.id, EV_CHANNEL_DELETE):
            return
        entry = await self.audit_entry(
            channel.guild, discord.AuditLogAction.channel_delete, target_id=channel.id
        )
        category = getattr(channel, "category", None)
        deleted_by = ""
        if entry:
            deleted_by = f"\n**Deleted By:** {entry.user}"
            if entry.reason:
                deleted_by += f"\n**Reason:** {entry.reason}"
        embed = LoggerEmbed.base(
            "🗑 Channel Deleted",
            LoggerEmbed.RED,
            description=(
                f"**Channel:** #{getattr(channel, 'name', str(channel))}\n"
                f"**Category:** {category.name if category else 'None'}"
                f"{deleted_by}"
            ),
        )
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
        embed = LoggerEmbed.base(
            "✏ Channel Renamed",
            LoggerEmbed.BLUE,
            description=(
                f"**Channel:** {after.mention}\n"
                f"**Before:** #{before.name}\n"
                f"**After:** #{after.name}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    async def _topic(self, before, after):
        if not db.is_enabled(after.guild.id, EV_CHANNEL_UPDATE):
            return
        embed = LoggerEmbed.base(
            "📝 Channel Topic Updated",
            LoggerEmbed.BLUE,
            description=f"**Channel:** {after.mention}",
        )
        LoggerEmbed.field(embed, "Before", before.topic or "*None*")
        LoggerEmbed.field(embed, "After", after.topic or "*None*")
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    async def _slowmode(self, before, after):
        if not db.is_enabled(after.guild.id, EV_CHANNEL_UPDATE):
            return
        embed = LoggerEmbed.base(
            "🐢 Slowmode Updated",
            LoggerEmbed.BLUE,
            description=(
                f"**Channel:** {after.mention}\n"
                f"**Before:** {before.slowmode_delay}s\n"
                f"**After:** {after.slowmode_delay}s"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)

    # ----- threads -----

    @commands.Cog.listener()
    async def on_thread_create(self, thread):
        if not db.is_enabled(thread.guild.id, EV_THREAD_CREATE):
            return
        embed = LoggerEmbed.base(
            "🧵 Thread Created",
            LoggerEmbed.GREEN,
            description=(
                f"**Thread:** {thread.name}\n"
                f"**Channel:** "
                f"{thread.parent.mention if thread.parent else 'Unknown'}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(thread.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_thread_delete(self, thread):
        if not db.is_enabled(thread.guild.id, EV_THREAD_DELETE):
            return
        embed = LoggerEmbed.base(
            "🗑 Thread Deleted",
            LoggerEmbed.RED,
            description=f"**Thread:** {thread.name}",
        )
        LoggerEmbed.finalize(embed)
        await self.send(thread.guild, SERVER, embed)
