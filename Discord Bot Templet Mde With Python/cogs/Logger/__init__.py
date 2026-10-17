"""Kush Bush Logger — per-category Discord event logging."""
from .messages import MessageLogger
from .members import MemberLogger
from .channels import ChannelLogger
from .emoji import EmojiLogger
from .moderation import ModerationLogger
from .voice import VoiceLogger
from .invites import InviteLogger
from .roles import RoleLogger
from .commands import LoggerCommands, log_toggle_group


def setup(bot):
    for cog in (
        MessageLogger,
        MemberLogger,
        ChannelLogger,
        EmojiLogger,
        ModerationLogger,
        VoiceLogger,
        InviteLogger,
        RoleLogger,
        LoggerCommands,
    ):
        bot.add_cog(cog(bot))
    bot.add_application_command(log_toggle_group)
