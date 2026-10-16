from .logger import Logger

from .database import database





class LoggerManager:

    def __init__(self, bot):

        self.bot = bot

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

    async def save(

        self,

        guild,

        category,

        payload

    ):

        database.save_event(

            guild.id,

            category,

            payload

        )

    def register(

        self,

        name,

        handler

    ):

        self.handlers[name] = handler

    def get(

        self,

        name

    ):

        return self.handlers.get(name)


manager = LoggerManager()