"""Logs moderation actions: bans, unbans, timeouts."""
import discord
from discord.ext import commands

from .audit import resolve_moderator
from .base import BaseLogger
from .config import MODERATION, EV_BAN, EV_UNBAN, EV_TIMEOUT
from .embeds import LoggerEmbed, user_line
from .database import db


class ModerationLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_member_ban(self, guild, user):
        if not db.is_enabled(guild.id, EV_BAN):
            return
        mod = await resolve_moderator(
            guild, self.bot, discord.AuditLogAction.ban, user.id, ("ban", "tempban")
        )
        # Havenly "User Banned" copy: description form with the
        # original's exact three lines, the banned user's pfp as the
        # thumbnail, and the moderator's pfp + "Banned by X" as the
        # author -- "X was banned by Y" framing. The footer is the
        # original's "Powered by Havenly Bot", re-applied AFTER
        # finalize() (the shared footer is now the same string, so
        # this just makes the ban embed's footer explicit).
        embed = LoggerEmbed.base("🔨 User Banned", LoggerEmbed.RED)
        embed.description = (
            f"**User:** {user.mention} [{user.name}] ({user.id})\n"
            f"**Moderator:** {mod['mention']} [{mod['name']}]\n"
            f"**Reason:** {mod['reason'] or 'No reason provided.'}"
        )
        embed.set_thumbnail(url=user.display_avatar.url)
        if mod["name"] != "Unknown":
            if mod["avatar_url"]:
                embed.set_author(
                    name=f"Banned by {mod['name']}",
                    icon_url=mod["avatar_url"],
                )
            else:
                embed.set_author(name=f"Banned by {mod['name']}")
        LoggerEmbed.finalize(embed)
        embed.set_footer(text="Powered by Havenly Bot")
        await self.send(guild, MODERATION, embed)

    @commands.Cog.listener()
    async def on_member_unban(self, guild, user):
        if not db.is_enabled(guild.id, EV_UNBAN):
            return
        mod = await resolve_moderator(
            guild, self.bot, discord.AuditLogAction.unban, user.id, ("unban",)
        )
        embed = LoggerEmbed.base(
            "♻ Member Unbanned",
            LoggerEmbed.GREEN,
            description=(
                f"**User:** {user_line(user)}\n"
                f"**Moderator:** {mod['mention']} [{mod['name']}]"
            ),
        )
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
            mod = await resolve_moderator(
                after.guild, self.bot, discord.AuditLogAction.member_update,
                after.id, ("timeout",),
            )
            embed = LoggerEmbed.base(
                "⏱ Member Timed Out",
                LoggerEmbed.RED,
                description=(
                    f"**User:** {user_line(after)}\n"
                    f"**Until:** "
                    f"{discord.utils.format_dt(after_to, style='F')}\n"
                    f"**Moderator:** {mod['mention']} [{mod['name']}]\n"
                    f"**Reason:** {mod['reason'] or 'No reason provided.'}"
                ),
            )
            LoggerEmbed.author(embed, after)
        else:
            embed = LoggerEmbed.base(
                "⏱ Timeout Removed",
                LoggerEmbed.GREEN,
                description=f"**User:** {user_line(after)}",
            )
            LoggerEmbed.author(embed, after)
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, MODERATION, embed)
