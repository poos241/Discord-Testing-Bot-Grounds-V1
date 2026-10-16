from .embeds import LoggerEmbed
from .constants import SERVER


class InviteEmbeds:

    @staticmethod
    async def created(bot, invite):

        embed = LoggerEmbed.base(

            "📨 Invite Created",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Code",

            invite.code

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            invite.channel.mention

        )

        LoggerEmbed.field(

            embed,

            "Uses",

            invite.max_uses or "Unlimited"

        )

        LoggerEmbed.field(

            embed,

            "Expires",

            invite.max_age or "Never"

        )

        await LoggerEmbed.send(

            bot,

            invite.guild,

            embed

        )

    #
    # -------------------------
    #

    @staticmethod
    async def deleted(bot, invite):

        embed = LoggerEmbed.base(

            "❌ Invite Deleted",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Code",

            invite.code

        )

        await LoggerEmbed.send(

            bot,

            invite.guild,

            embed

        )