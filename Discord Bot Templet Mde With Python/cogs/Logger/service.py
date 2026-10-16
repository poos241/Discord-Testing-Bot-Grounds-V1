from .logger import Logger


class LoggerService:

    def __init__(self, bot):

        self.logger = Logger(bot)

    async def dispatch(

        self,

        guild,

        category,

        embed

    ):

        await self.logger.send(

            guild,

            category,

            embed

        )