"""Logs member joins, leaves, and profile/role changes."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import MEMBER, COLORS
from .embeds import LoggerEmbed


class MemberLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_member_join(self, member):
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
        embed = LoggerEmbed.base("✏ Nickname Changed", COLORS[MEMBER])
        LoggerEmbed.author(embed, after)
        LoggerEmbed.field(embed, "Before", before.nick or "*None*")
        LoggerEmbed.field(embed, "After", after.nick or "*None*")
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, MEMBER, embed)

    async def _avatar_change(self, member):
        embed = LoggerEmbed.base("🖼 Avatar Changed", COLORS[MEMBER])
        LoggerEmbed.author(embed, member)
        embed.set_image(url=member.display_avatar.url)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    async def _role_change(self, member, role, added):
        embed = LoggerEmbed.base(
            "➕ Role Added" if added else "➖ Role Removed",
            discord.Color.green() if added else discord.Color.red(),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.field(embed, "Role", role.mention, inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)
