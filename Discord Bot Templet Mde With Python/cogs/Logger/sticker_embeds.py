from .embeds import LoggerEmbed

from .constants import SERVER


class StickerEmbeds:

    @staticmethod
    async def created(

        bot,

        sticker

    ):

        embed = LoggerEmbed.base(

            "🎨 Sticker Created",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Name",

            sticker.name

        )

        LoggerEmbed.field(

            embed,

            "Description",

            sticker.description

        )

        await LoggerEmbed.send(

            bot,

            sticker.guild,

            embed

        )

    #
    # ---------------------
    #

    @staticmethod
    async def deleted(

        bot,

        sticker

    ):

        embed = LoggerEmbed.base(

            "🗑 Sticker Deleted",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Name",

            sticker.name

        )

        await LoggerEmbed.send(

            bot,

            sticker.guild,

            embed

        )

    #
    # ---------------------
    #

    @staticmethod
    async def updated(

        bot,

        before,

        after

    ):

        embed = LoggerEmbed.base(

            "✏ Sticker Updated",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Old Name",

            before.name

        )

        LoggerEmbed.field(

            embed,

            "New Name",

            after.name

        )

        LoggerEmbed.field(

            embed,

            "Description",

            after.description

        )

        await LoggerEmbed.send(

            bot,

            after.guild,

            embed

        )