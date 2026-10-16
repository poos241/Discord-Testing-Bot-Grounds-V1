from .embeds import LoggerEmbed
from .constants import SERVER


class EmojiEmbeds:

    @staticmethod
    async def created(bot, emoji):

        embed = LoggerEmbed.base(

            "😀 Emoji Created",

            SERVER

        )

        embed.set_thumbnail(

            url=emoji.url

        )

        LoggerEmbed.field(

            embed,

            "Name",

            emoji.name

        )

        await LoggerEmbed.send(

            bot,

            emoji.guild,

            embed

        )

    

    @staticmethod
    async def deleted(bot, emoji):

        embed = LoggerEmbed.base(

            "❌ Emoji Deleted",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Name",

            emoji.name

        )

        await LoggerEmbed.send(

            bot,

            emoji.guild,

            embed

        )

  

    @staticmethod
    async def renamed(

        bot,

        before,

        after

    ):

        embed = LoggerEmbed.base(

            "✏ Emoji Renamed",

            SERVER

        )

        embed.set_thumbnail(

            url=after.url

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.name

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.name

        )

        await LoggerEmbed.send(

            bot,

            after.guild,

            embed

        )