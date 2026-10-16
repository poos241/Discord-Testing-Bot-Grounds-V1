import discord

from cogs.Logger.utils import send_log

from .embeds import LoggerEmbed
from .constants import CHANNEL


class ChannelEmbeds:

    @staticmethod
    async def created(bot, channel):

        embed = LoggerEmbed.base(
            "📁 Channel Created",
            CHANNEL
        )

        LoggerEmbed.field(
            embed,
            "Name",
            channel.name
        )

        LoggerEmbed.field(
            embed,
            "ID",
            channel.id
        )

        LoggerEmbed.field(
            embed,
            "Category",
            channel.category.name if channel.category else "None"
        )

        LoggerEmbed.field(
            embed,
            "Type",
            str(channel.type)
        )

        await send_log(bot, channel.guild.id, "server", embed=embed)

    #
    # -------------------------
    #

    @staticmethod
    async def deleted(bot, channel):

        embed = LoggerEmbed.base(
            "🗑 Channel Deleted",
            CHANNEL
        )

        LoggerEmbed.field(
            embed,
            "Name",
            channel.name
        )

        LoggerEmbed.field(
            embed,
            "Category",
            channel.category.name if channel.category else "None"
        )

        await send_log(bot, channel.guild.id, "server", embed=embed)

    #
    # -------------------------
    #

    @staticmethod
    async def renamed(bot, before, after):

        embed = LoggerEmbed.base(
            "✏ Channel Renamed",
            CHANNEL
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

        await send_log(bot, after.guild.id, "server", embed=embed)

    #
    # -------------------------
    #

    @staticmethod
    async def topic(bot, before, after):

        embed = LoggerEmbed.base(
            "📝 Topic Updated",
            CHANNEL
        )

        LoggerEmbed.field(
            embed,
            "Old",
            before.topic
        )

        LoggerEmbed.field(
            embed,
            "New",
            after.topic
        )

        await send_log(bot, after.guild.id, "server", embed=embed)

    #
    # -------------------------
    #

    @staticmethod
    async def slowmode(bot, before, after):

        embed = LoggerEmbed.base(
            "🐢 Slowmode Updated",
            CHANNEL
        )

        LoggerEmbed.field(
            embed,
            "Before",
            before.slowmode_delay
        )

        LoggerEmbed.field(
            embed,
            "After",
            after.slowmode_delay
        )

        await send_log(bot, after.guild.id, "server", embed=embed)

    #
    # -------------------------
    #

    @staticmethod
    async def nsfw(bot, before, after):

        embed = LoggerEmbed.base(
            "🔞 NSFW Updated",
            CHANNEL
        )

        LoggerEmbed.field(
            embed,
            "Enabled",
            after.nsfw
        )

        await send_log(bot, before.guild.id, after.guild.id, "server", embed=embed)