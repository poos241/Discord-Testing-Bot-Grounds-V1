"""Logs voice channel joins, leaves, moves, and mute/deafen changes."""
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import (
    MEMBER,
    EV_VOICE_JOIN, EV_VOICE_LEAVE, EV_VOICE_MOVE, EV_VOICE_MUTE,
)
from .database import db
from .embeds import LoggerEmbed, user_line


class VoiceLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild

        # Join / leave / move
        if before.channel is None and after.channel is not None:
            if db.is_enabled(guild.id, EV_VOICE_JOIN):
                await self._join(member, after.channel)
        elif before.channel is not None and after.channel is None:
            if db.is_enabled(guild.id, EV_VOICE_LEAVE):
                await self._leave(member, before.channel)
        elif before.channel != after.channel:
            if db.is_enabled(guild.id, EV_VOICE_MOVE):
                await self._move(member, before.channel, after.channel)

        # Mute / deafen changes (only meaningful while in a channel)
        if after.channel is not None and db.is_enabled(guild.id, EV_VOICE_MUTE):
            changes = []
            if before.mute != after.mute:
                changes.append(("Server Muted", after.mute))
            if before.deaf != after.deaf:
                changes.append(("Server Deafened", after.deaf))
            if before.self_mute != after.self_mute:
                changes.append(("Self Muted", after.self_mute))
            if before.self_deaf != after.self_deaf:
                changes.append(("Self Deafened", after.self_deaf))
            if before.self_stream != after.self_stream:
                changes.append(("Streaming", after.self_stream))
            if before.self_video != after.self_video:
                changes.append(("Camera On", after.self_video))
            for name, state in changes:
                await self._voice_flag(member, after.channel, name, state)

    async def _join(self, member, channel):
        embed = LoggerEmbed.base(
            "🔊 Joined Voice",
            LoggerEmbed.GREEN,
            description=(
                f"**User:** {user_line(member)}\n"
                f"**Channel:** {channel.mention}"
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    async def _leave(self, member, channel):
        embed = LoggerEmbed.base(
            "🔇 Left Voice",
            LoggerEmbed.RED,
            description=(
                f"**User:** {user_line(member)}\n"
                f"**Channel:** {channel.mention}"
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    async def _move(self, member, before, after):
        embed = LoggerEmbed.base(
            "🔀 Moved Voice Channel",
            LoggerEmbed.BLUE,
            description=(
                f"**User:** {user_line(member)}\n"
                f"**From:** {before.mention}\n"
                f"**To:** {after.mention}"
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    async def _voice_flag(self, member, channel, name, state):
        embed = LoggerEmbed.base(
            f"🎙 {name}: {'On' if state else 'Off'}",
            LoggerEmbed.BLUE,
            description=(
                f"**User:** {user_line(member)}\n"
                f"**Channel:** {channel.mention}"
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)
