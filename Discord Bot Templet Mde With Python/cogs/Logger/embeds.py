"""Shared embed builders for log messages."""
import discord

from .config import FOOTER_TEXT


class LoggerEmbed:
    @staticmethod
    def base(title, color):
        return discord.Embed(
            title=title,
            color=color,
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def author(embed, user):
        embed.set_author(
            name=f"{user} ({user.id})",
            icon_url=user.display_avatar.url,
        )
        return embed

    @staticmethod
    def footer(embed, text=FOOTER_TEXT):
        embed.set_footer(text=text)
        return embed

    @staticmethod
    def field(embed, name, value, inline=False):
        text = str(value) if value not in (None, "") else "None"
        if len(text) > 1024:
            text = text[:1020] + "..."
        embed.add_field(name=name, value=text, inline=inline)
        return embed

    @staticmethod
    def finalize(embed):
        """Apply the standard footer. Call after building the embed."""
        return LoggerEmbed.footer(embed)
