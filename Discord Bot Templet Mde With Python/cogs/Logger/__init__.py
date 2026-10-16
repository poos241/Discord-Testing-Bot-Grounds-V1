"""Kush Bush Logger — per-category Discord event logging."""
from .messages import MessageLogger
from .members import MemberLogger
from .channels import ChannelLogger
from .emoji import EmojiLogger
from .moderation import ModerationLogger
from .commands import LoggerCommands


def setup(bot):
    for cog in (
        MessageLogger,
        MemberLogger,
        ChannelLogger,
        EmojiLogger,
        ModerationLogger,
        LoggerCommands,
    ):
        bot.add_cog(cog(bot))
