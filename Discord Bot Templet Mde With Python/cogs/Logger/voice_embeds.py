from email.mime import message

from cogs.Logger.utils import send_log

from .embeds import LoggerEmbed

from .constants import VOICE


class VoiceEmbeds:

    @staticmethod
    async def joined(

        bot,

        member,

        channel

    ):

        embed = LoggerEmbed.base(

            "🔊 Voice Joined",

            VOICE

        )

        LoggerEmbed.author(

            embed,

            member

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            channel.mention

        )

        await send_log(bot, member.guild.id, "server", embed=embed)
    #
    # -----------------------
    #

    @staticmethod
    async def left(

        bot,

        member,

        channel

    ):

        embed = LoggerEmbed.base(

            "🔈 Voice Left",

            VOICE

        )

        LoggerEmbed.author(

            embed,

            member

        )

        LoggerEmbed.author(
        
            embed,

            member

        )
        
        LoggerEmbed.field(

            embed,

            "Channel",

            channel.mention

        )

        await send_log(bot, member.guild.id, "server", embed=embed)
    #
    # -----------------------
    #

    @staticmethod
    async def moved(

        bot,

        member,

        before,

        after

    ):

        embed = LoggerEmbed.base(

            "🎧 Voice Moved",

            VOICE

        )

        LoggerEmbed.author(

            embed,

            member

        )

        LoggerEmbed.field(

            embed,

            "From",

            before.mention

        )

        LoggerEmbed.field(

            embed,

            "To",

            after.mention

        )

        await send_log(bot, member.guild.id, "server", embed=embed)