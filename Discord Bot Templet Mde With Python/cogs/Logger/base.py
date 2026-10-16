from discord.ext import commands

from .logger import Logger

from .audit import Audit


class BaseLogger(commands.Cog):

    def __init__(self, bot):

        self.bot = bot

        self.logger = Logger(bot)

    #
    # -------------------------
    #

    async def send(

        self,

        guild,

        event,

        embed

    ):

        await self.logger.send(

            guild,

            event,

            embed

        )

    #
    # -------------------------
    #

    async def audit(

        self,

        guild,

        action

    ):

        return await Audit.latest(

            guild,

            action

        )