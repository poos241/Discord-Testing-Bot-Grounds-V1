"""Logs invite create/delete events."""
from discord.ext import commands

from .base import BaseLogger
from .config import SERVER, EV_INVITE_CREATE, EV_INVITE_DELETE
from .database import db
from .embeds import LoggerEmbed


class InviteLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_invite_create(self, invite):
        if not db.is_enabled(invite.guild.id, EV_INVITE_CREATE):
            return
        if invite.max_age:
            mins, secs = divmod(invite.max_age, 60)
            hrs, mins = divmod(mins, 60)
            expiry = f"{hrs}h {mins}m" if hrs else f"{mins}m {secs}s"
        else:
            expiry = "Never"
        embed = LoggerEmbed.base(
            "📨 Invite Created",
            LoggerEmbed.GREEN,
            description=(
                f"**Code:** `{invite.code}`\n"
                f"**Channel:** "
                f"{invite.channel.mention if invite.channel else 'Unknown'}\n"
                f"**Created By:** "
                f"{invite.inviter if invite.inviter else 'Unknown'}\n"
                f"**Max Uses:** "
                f"{invite.max_uses if invite.max_uses else 'Unlimited'}\n"
                f"**Expires:** {expiry}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(invite.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_invite_delete(self, invite):
        if not db.is_enabled(invite.guild.id, EV_INVITE_DELETE):
            return
        embed = LoggerEmbed.base(
            "❌ Invite Deleted",
            LoggerEmbed.RED,
            description=(
                f"**Code:** `{invite.code}`\n"
                f"**Channel:** "
                f"{invite.channel.mention if invite.channel else 'Unknown'}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(invite.guild, SERVER, embed)
