import discord

from .embeds import LoggerEmbed
from .constants import MEMBER


class MemberEmbeds:

    @staticmethod
    async def member_join(bot, member):

        embed = LoggerEmbed.base(
            "📥 Member Joined",
            MEMBER
        )

        LoggerEmbed.author(embed, member)

        LoggerEmbed.field(
            embed,
            "Account Created",
            discord.utils.format_dt(
                member.created_at,
                style="R"
            )
        )

        LoggerEmbed.field(
            embed,
            "Member Count",
            member.guild.member_count
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await LoggerEmbed.send(
            bot,
            member.guild,
            embed
        )

    #
    # -----------------------------
    #

    @staticmethod
    async def member_leave(bot, member):

        embed = LoggerEmbed.base(
            "📤 Member Left",
            MEMBER
        )

        LoggerEmbed.author(embed, member)

        LoggerEmbed.field(
            embed,
            "Joined",
            discord.utils.format_dt(
                member.joined_at,
                style="R"
            )
        )

        embed.set_thumbnail(
            url=member.display_avatar.url
        )

        await LoggerEmbed.send(
            bot,
            member.guild,
            embed
        )

    #
    # -----------------------------
    #

    @staticmethod
    async def nickname_change(bot, before, after):

        embed = LoggerEmbed.base(
            "✏ Nickname Changed",
            MEMBER
        )

        LoggerEmbed.author(
            embed,
            after
        )

        LoggerEmbed.field(
            embed,
            "Before",
            before.nick
        )

        LoggerEmbed.field(
            embed,
            "After",
            after.nick
        )

        await LoggerEmbed.send(
            bot,
            after.guild,
            embed
        )

    #
    # -----------------------------
    #

    @staticmethod
    async def avatar_change(bot, before, after):

        embed = LoggerEmbed.base(
            "🖼 Avatar Changed",
            MEMBER
        )

        LoggerEmbed.author(
            embed,
            after
        )

        if after.display_avatar:

            embed.set_image(
                url=after.display_avatar.url
            )

        await LoggerEmbed.send(
            bot,
            after.guild,
            embed
        )

    #
    # -----------------------------
    #

    @staticmethod
    async def username_change(bot, before, after):

        embed = LoggerEmbed.base(
            "👤 Username Changed",
            MEMBER
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