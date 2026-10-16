"""Logs invite create/delete events."""
from discord.ext import commands

from .base import BaseLogger
from .config import SERVER, COLORS, EV_INVITE_CREATE, EV_INVITE_DELETE
from .database import db
from .embeds import LoggerEmbed


class InviteLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if not db.is_enabled(invite.guild.id, EV_INVITE_CREATE):
            return
        embed = LoggerEmbed.base("📨 Invite Created", COLORS[SERVER])
        LoggerEmbed.field(embed, "Code", f"`{invite.code}`", inline=True)
        LoggerEmbed.field(
            embed, "Channel",
            invite.channel.mention if invite.channel else "Unknown",
            inline=True,
        )
        LoggerEmbed.field(
            embed, "Created By",
            str(invite.inviter) if invite.inviter else "Unknown",
            inline=True,
        )
        LoggerEmbed.field(
            embed, "Max Uses",
            invite.max_uses if invite.max_uses else "Unlimited",
            inline=True,
        )
        if invite.max_age:
            mins, secs = divmod(invite.max_age, 60)
            hrs, mins = divmod(mins, 60)
            expiry = f"{hrs}h {mins}m" if hrs else f"{mins}m {secs}s"
        else:
            expiry = "Never"
        LoggerEmbed.field(embed, "Expires", expiry, inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(invite.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if not db.is_enabled(invite.guild.id, EV_INVITE_DELETE):
            return
        embed = LoggerEmbed.base("❌ Invite Deleted", COLORS[SERVER])
        LoggerEmbed.field(embed, "Code", f"`{invite.code}`", inline=True)
        LoggerEmbed.field(
            embed, "Channel",
            invite.channel.mention if invite.channel else "Unknown",
            inline=True,
        )
        LoggerEmbed.finalize(embed)
        await self.send(invite.guild, SERVER, embed)
