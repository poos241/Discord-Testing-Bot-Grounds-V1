"""Logs member joins, leaves, and profile/role changes."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import (MEMBER, COLORS, MODERATION, EV_MEMBER_JOIN, EV_MEMBER_LEAVE,
    EV_MEMBER_KICK, EV_NICKNAME, EV_AVATAR, EV_ROLE_MEMBER)
from .embeds import LoggerEmbed
from .database import db


class MemberLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not db.is_enabled(member.guild.id, EV_MEMBER_JOIN):
            return
        embed = LoggerEmbed.base("📥 Member Joined", COLORS[MEMBER])
        LoggerEmbed.author(embed, member)
        LoggerEmbed.field(
            embed, "Account Created",
            discord.utils.format_dt(member.created_at, style="R"),
            inline=True,
        )
        LoggerEmbed.field(embed, "Member Count", member.guild.member_count, inline=True)
        embed.set_thumbnail(url=member.display_avatar.url)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Distinguish kicks from plain leaves via the audit log.
        entry = await self.audit_entry(
            member.guild, discord.AuditLogAction.kick, target_id=member.id
        )
        if entry and db.is_enabled(member.guild.id, EV_MEMBER_KICK):
            age = (discord.utils.utcnow() - entry.created_at).total_seconds()
            if age < 15:
                embed = LoggerEmbed.base("👢 Member Kicked", COLORS[MODERATION])
                LoggerEmbed.author(embed, member)
                LoggerEmbed.field(embed, "Moderator", str(entry.user), inline=True)
                LoggerEmbed.field(embed, "Reason", entry.reason or "No reason provided.")
                embed.set_thumbnail(url=member.display_avatar.url)
                LoggerEmbed.finalize(embed)
                await self.send(member.guild, MODERATION, embed)
                return
        if not db.is_enabled(member.guild.id, EV_MEMBER_LEAVE):
            return
        embed = LoggerEmbed.base("📤 Member Left", COLORS[MEMBER])
        LoggerEmbed.author(embed, member)
        if member.joined_at:
            LoggerEmbed.field(
                embed, "Joined",
                discord.utils.format_dt(member.joined_at, style="R"),
                inline=True,
            )
        embed.set_thumbnail(url=member.display_avatar.url)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick != after.nick:
            await self._nickname_change(before, after)
        if before.display_avatar != after.display_avatar:
            await self._avatar_change(after)
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        for role in added:
            await self._role_change(after, role, added=True)
        for role in removed:
            await self._role_change(after, role, added=False)

    async def _nickname_change(self, before, after):
        if not db.is_enabled(after.guild.id, EV_NICKNAME):
            return
        embed = LoggerEmbed.base("✏ Nickname Changed", COLORS[MEMBER])
        LoggerEmbed.author(embed, after)
        LoggerEmbed.field(embed, "Before", before.nick or "*None*")
        LoggerEmbed.field(embed, "After", after.nick or "*None*")
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, MEMBER, embed)

    async def _avatar_change(self, member):
        if not db.is_enabled(member.guild.id, EV_AVATAR):
            return
        embed = LoggerEmbed.base("🖼 Avatar Changed", COLORS[MEMBER])
        LoggerEmbed.author(embed, member)
        embed.set_image(url=member.display_avatar.url)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    async def _role_change(self, member, role, added):
        if not db.is_enabled(member.guild.id, EV_ROLE_MEMBER):
            return
        embed = LoggerEmbed.base(
            "➕ Role Added" if added else "➖ Role Removed",
            discord.Color.green() if added else discord.Color.red(),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.field(embed, "Role", role.mention, inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)
