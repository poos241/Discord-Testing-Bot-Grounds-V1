from .embeds import LoggerEmbed
from .constants import CHANNEL


class ThreadEmbeds:

    @staticmethod
    async def created(bot, thread):

        embed = LoggerEmbed.base(

            "🧵 Thread Created",

            CHANNEL

        )

        LoggerEmbed.field(

            embed,

            "Name",

            thread.name

        )

        LoggerEmbed.field(

            embed,

            "Parent",

            thread.parent.mention

        )

        await LoggerEmbed.send(

            bot,

            thread.guild,

            embed

        )

    #
    # ------------------------
    #

    @staticmethod
    async def deleted(bot, thread):

        embed = LoggerEmbed.base(

            "🗑 Thread Deleted",

            CHANNEL

        )

        LoggerEmbed.field(

            embed,

            "Name",

            thread.name

        )

        await LoggerEmbed.send(

            bot,

            thread.guild,

            embed

        )

    #
    # ------------------------
    #

    @staticmethod
    async def archived(bot, before, after):

        embed = LoggerEmbed.base(

            "📦 Thread Archived",

            CHANNEL

        )

        LoggerEmbed.field(

            embed,

            "Thread",

            after.name

        )

        await LoggerEmbed.send(

            bot,

            after.guild,

            embed

        )

    #
    # ------------------------
    #

    @staticmethod
    async def locked(bot, before, after):

        embed = LoggerEmbed.base(

            "🔒 Thread Locked",

            CHANNEL

        )

        LoggerEmbed.field(

            embed,

            "Thread",

            after.name

        )

        await LoggerEmbed.send(

            bot,

            after.guild,

            embed

        )