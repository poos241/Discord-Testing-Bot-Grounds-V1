"""Havenly Bot Logger — per-category Discord event logging."""
from config import WORKER_MODE
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
    # LoggerCommands is loaded in BOTH modes: on the worker it provides
    # the /logs setup/change_channel/settings commands (worker-only
    # since the 2026-11-12 command split, Option C), and on the main
    # bot it runs the event-history prune loop (gated to main-only in
    # commands.py -- in main mode the cog has no commands, only the loop).
    bot.add_cog(LoggerCommands(bot))
    if WORKER_MODE:
        # Worker-only: the /log_toggle commands (setup). The 8
        # event-listener cogs below are NOT loaded here -- loading them
        # would log every message/member/role event twice.
        bot.add_application_command(log_toggle_group)
    else:
        # Main bot only: the real-time event listeners + the role-batch
        # flush loop (MemberLogger). The worker must never run these.
        for cog in (
            MessageLogger,
            MemberLogger,
            ChannelLogger,
            EmojiLogger,
            ModerationLogger,
            VoiceLogger,
            InviteLogger,
            RoleLogger,
        ):
            bot.add_cog(cog(bot))
