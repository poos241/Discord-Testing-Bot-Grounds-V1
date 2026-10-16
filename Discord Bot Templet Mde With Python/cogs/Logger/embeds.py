import discord

from .constants import *


class LoggerEmbed:

    @staticmethod
    def base(title: str, color: discord.Color):

        return discord.Embed(
            title=title,
            color=color,
            timestamp=discord.utils.utcnow()
        )

    @staticmethod
    def author(embed: discord.Embed, user):

        embed.set_author(
            name=f"{user} ({user.id})",
            icon_url=user.display_avatar.url
        )

        return embed

    @staticmethod
    def footer(embed: discord.Embed, text="Kush Bush Logger"):

        embed.set_footer(text=text)

        return embed

    @staticmethod
    def thumbnail(embed, url):

        embed.set_thumbnail(url=url)

        return embed

    @staticmethod
    def image(embed, url):

        embed.set_image(url=url)

        return embed

    @staticmethod
    def field(

        embed,

        name,

        value,

        inline=False

    ):

        if value is None:

            value = "None"

        value = str(value)

        if value == "":

            value = "None"

        if len(value) > 1024:

            value = value[:1020] + "..."

        embed.add_field(

            name=name,

            value=value,

            inline=inline

        )

        return embed

    @staticmethod
    def channel(embed, channel):

        embed.add_field(

            name="Channel",

            value=channel.mention,

            inline=True

        )

        return embed

    @staticmethod
    def member(embed, member):

        embed.add_field(

            name="Member",

            value=f"{member.mention}\n`{member.id}`",

            inline=True

        )

        return embed

    @staticmethod
    def moderator(embed, moderator):

        embed.add_field(

            name="Moderator",

            value=f"{moderator.mention}\n`{moderator.id}`",

            inline=True

        )

        return embed

    @staticmethod
    def reason(embed, reason):

        embed.add_field(

            name="Reason",

            value=reason or "No reason provided.",

            inline=False

        )

        return embed