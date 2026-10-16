from .database import database

from .commands import LoggerCommands
from .messages import MessageLogger
from .members import MemberLogger
from .voice import VoiceLogger
from .roles import RoleLogger
from .channels import ChannelLogger
from .server import ServerLogger
from .emoji import EmojiLogger
from .sticker import StickerLogger
from .moderation import ModerationLogger


def setup(bot):

    bot.add_cog(LoggerCommands(bot))

    bot.add_cog(MessageLogger(bot))

    bot.add_cog(MemberLogger(bot))

    bot.add_cog(VoiceLogger(bot))

    bot.add_cog(RoleLogger(bot))

    bot.add_cog(ChannelLogger(bot))

    bot.add_cog(ServerLogger(bot))

    bot.add_cog(EmojiLogger(bot))

    bot.add_cog(StickerLogger(bot))

    bot.add_cog(ModerationLogger(bot))