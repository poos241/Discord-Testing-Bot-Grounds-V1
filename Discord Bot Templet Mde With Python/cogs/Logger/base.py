"""Base cog all Logger cogs extend."""
from discord.ext import commands

from .logger import Logger
from .audit import Audit


class BaseLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.logger = Logger(bot)

    async def send(self, guild, category, embed):
        await self.logger.send(guild, category, embed)

    async def audit_entry(self, guild, action, target_id=None):
        return await Audit.latest(guild, action, target_id=target_id)
