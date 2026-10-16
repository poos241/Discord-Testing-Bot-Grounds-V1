"""Logs emoji create/delete/rename events."""
from discord.ext import commands

from .base import BaseLogger
from .config import SERVER, COLORS
from .embeds import LoggerEmbed


class EmojiLogger(BaseLogger):
    @commands.Cog.listener()
    async def on_guild_emojis_update(self, guild, before, after):
        before_ids = {e.id: e for e in before}
        after_ids = {e.id: e for e in after}

        for emoji_id, emoji in after_ids.items():
            if emoji_id not in before_ids:
                await self._created(guild, emoji)
            elif before_ids[emoji_id].name != emoji.name:
                await self._renamed(guild, before_ids[emoji_id], emoji)

        for emoji_id, emoji in before_ids.items():
            if emoji_id not in after_ids:
                await self._deleted(guild, emoji)

    async def _created(self, guild, emoji):
        embed = LoggerEmbed.base("😀 Emoji Created", COLORS[SERVER])
        embed.set_thumbnail(url=emoji.url)
        LoggerEmbed.field(embed, "Name", f":{emoji.name}:")
        LoggerEmbed.finalize(embed)
        await self.send(guild, SERVER, embed)

    async def _deleted(self, guild, emoji):
        embed = LoggerEmbed.base("❌ Emoji Deleted", COLORS[SERVER])
        LoggerEmbed.field(embed, "Name", f":{emoji.name}:")
        LoggerEmbed.finalize(embed)
        await self.send(guild, SERVER, embed)

    async def _renamed(self, guild, before, after):
        embed = LoggerEmbed.base("✏ Emoji Renamed", COLORS[SERVER])
        embed.set_thumbnail(url=after.url)
        LoggerEmbed.field(embed, "Before", f":{before.name}:")
        LoggerEmbed.field(embed, "After", f":{after.name}:")
        LoggerEmbed.finalize(embed)
        await self.send(guild, SERVER, embed)
