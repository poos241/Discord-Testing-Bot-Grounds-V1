from cogs.Logger.constants import MESSAGE

from .base import BaseLogger
class MessageHandler(BaseLogger):

    async def delete(

        self,

        message

    ):

        await self.log(

            message.guild,

            "🗑 Message Deleted",

            MESSAGE,

            [

                (

                    "Author",

                    str(message.author),

                    False

                ),

                (

                    "Channel",

                    message.channel.mention,

                    False

                ),

                (

                    "Content",

                    message.content,

                    False

                )

            ]

        )