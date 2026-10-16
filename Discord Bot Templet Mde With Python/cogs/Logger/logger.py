import discord

from .config import LOG_TYPES

from .utils import get_log_channel


class Logger:

    def __init__(

        self,

        bot

    ):

        self.bot = bot

    async def send(

        self,

        guild,

        event,

        embed

    ):

        category = LOG_TYPES.get(

            event,

            event

        )

        channel_id = get_log_channel( 
            guild.id, 
            category 
        )

        if channel_id is None:

            return

        channel = guild.get_channel(

            channel_id

        )

        if channel is None:

            try:

                channel = await self.bot.fetch_channel(

                    channel_id

                )

            except Exception:

                return

        try:

            await channel.send(

                embed=embed

            )

        except discord.Forbidden:

            return

        except discord.HTTPException:

            return