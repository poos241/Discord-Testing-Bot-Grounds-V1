"""Logs moderation actions: bans, unbans, timeouts."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import MODERATION, COLORS, EV_BAN, EV_UNBAN, EV_TIMEOUT
from .embeds import LoggerEmbed
from .database import db


class ModerationLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if not db.is_enabled(guild.id, EV_BAN):
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.ban, target_id=user.id)
        embed = LoggerEmbed.base("🔨 Member Banned", COLORS[MODERATION])
        LoggerEmbed.field(embed, "User", f"{user} (`{user.id}`)")
        LoggerEmbed.field(embed, "Moderator", str(entry.user) if entry else "Unknown", inline=True)
        LoggerEmbed.field(embed, "Reason", (entry.reason if entry else None) or "No reason provided.")
        LoggerEmbed.finalize(embed)
        await self.send(guild, MODERATION, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if not db.is_enabled(guild.id, EV_UNBAN):
            return
        entry = await self.audit_entry(guild, discord.AuditLogAction.unban, target_id=user.id)
        embed = LoggerEmbed.base("♻ Member Unbanned", COLORS[MODERATION])
        LoggerEmbed.field(embed, "User", f"{user} (`{user.id}`)")
        LoggerEmbed.field(embed, "Moderator", str(entry.user) if entry else "Unknown", inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(guild, MODERATION, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if not db.is_enabled(after.guild.id, EV_TIMEOUT):
            return
        before_to = getattr(before, "timed_out_until", None)
        after_to = getattr(after, "timed_out_until", None)
        if before_to == after_to:
            return
        if after_to is not None:
            entry = await self.audit_entry(
                after.guild, discord.AuditLogAction.member_update, target_id=after.id
            )
            embed = LoggerEmbed.base("⏱ Member Timed Out", COLORS[MODERATION])
            LoggerEmbed.author(embed, after)
            LoggerEmbed.field(
                embed, "Until",
                discord.utils.format_dt(after_to, style="F"),
                inline=True,
            )
            LoggerEmbed.field(embed, "Moderator", str(entry.user) if entry else "Unknown", inline=True)
            LoggerEmbed.field(embed, "Reason", (entry.reason if entry else None) or "No reason provided.")
        else:
            embed = LoggerEmbed.base("⏱ Timeout Removed", COLORS[MODERATION])
            LoggerEmbed.author(embed, after)
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, MODERATION, embed)
