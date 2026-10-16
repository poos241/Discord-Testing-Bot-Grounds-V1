from .embeds import LoggerEmbed

from .constants import ROLE


class RoleEmbeds:

    @staticmethod
    async def created(

        bot,

        guild,

        role

    ):

        embed = LoggerEmbed.base(

            "➕ Role Created",

            ROLE

        )

        LoggerEmbed.field(

            embed,

            "Role",

            role.name

        )

        LoggerEmbed.field(

            embed,

            "Color",

            str(role.color)

        )

        LoggerEmbed.field(

            embed,

            "Position",

            role.position

        )

        await LoggerEmbed.send(

            bot,

            guild,

            embed

        )

    #
    # ----------------------------
    #

    @staticmethod
    async def deleted(

        bot,

        guild,

        role

    ):

        embed = LoggerEmbed.base(

            "➖ Role Deleted",

            ROLE

        )

        LoggerEmbed.field(

            embed,

            "Role",

            role.name

        )

        await LoggerEmbed.send(

            bot,

            guild,

            embed

        )

    #
    # ----------------------------
    #

    @staticmethod
    async def updated(

        bot,

        guild,

        before,

        after

    ):

        embed = LoggerEmbed.base(

            "✏ Role Updated",

            ROLE

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

            guild,

            embed

        )