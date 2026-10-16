"""Logs role create/delete/update events."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import (
    SERVER, COLORS,
    EV_ROLE_CREATE, EV_ROLE_DELETE, EV_ROLE_UPDATE,
)
from .database import db
from .embeds import LoggerEmbed


class RoleLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_guild_role_create(self, role):
        if not db.is_enabled(role.guild.id, EV_ROLE_CREATE):
            return
        entry = await self.audit_entry(
            role.guild, discord.AuditLogAction.role_create, target_id=role.id
        )
        embed = LoggerEmbed.base("✨ Role Created", COLORS[SERVER])
        LoggerEmbed.field(embed, "Role", role.mention, inline=True)
        LoggerEmbed.field(embed, "Color", str(role.color), inline=True)
        if entry:
            LoggerEmbed.field(embed, "Created By", str(entry.user), inline=True)
        LoggerEmbed.finalize(embed)
        await self.send(role.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_guild_role_delete(self, role):
        if not db.is_enabled(role.guild.id, EV_ROLE_DELETE):
            return
        entry = await self.audit_entry(
            role.guild, discord.AuditLogAction.role_delete, target_id=role.id
        )
        embed = LoggerEmbed.base("🗑 Role Deleted", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", f"@{role.name}", inline=True)
        if entry:
            LoggerEmbed.field(embed, "Deleted By", str(entry.user), inline=True)
            if entry.reason:
                LoggerEmbed.field(embed, "Reason", entry.reason)
        LoggerEmbed.finalize(embed)
        await self.send(role.guild, SERVER, embed)

    @commands.Cog.listener()
    async def on_guild_role_update(self, before, after):
        if not db.is_enabled(after.guild.id, EV_ROLE_UPDATE):
            return
        changes = []
        if before.name != after.name:
            changes.append(("Name", f"{before.name} → {after.name}"))
        if before.color != after.color:
            changes.append(("Color", f"{before.color} → {after.color}"))
        if before.mentionable != after.mentionable:
            changes.append(("Mentionable", "On" if after.mentionable else "Off"))
        if before.hoist != after.hoist:
            changes.append(("Displayed Separately", "On" if after.hoist else "Off"))
        # Permission diff
        added = [p for p, v in after.permissions if v and not getattr(before.permissions, p)]
        removed = [p for p, v in before.permissions if v and not getattr(after.permissions, p)]
        if added:
            changes.append(("Permissions Added", ", ".join(added)))
        if removed:
            changes.append(("Permissions Removed", ", ".join(removed)))
        if not changes:
            return
        embed = LoggerEmbed.base("✏ Role Updated", COLORS[SERVER])
        LoggerEmbed.field(embed, "Role", after.mention, inline=True)
        for name, value in changes:
            LoggerEmbed.field(embed, name, value)
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, SERVER, embed)
