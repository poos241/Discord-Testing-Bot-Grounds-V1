"""Shared configuration for the Logger package."""
import discord

# Log categories. Used as DB keys, channel-name keys, and send() categories.
MESSAGE = "message"
MEMBER = "member"
SERVER = "server"
MODERATION = "moderation"

CATEGORIES = (MESSAGE, MEMBER, SERVER, MODERATION)

# Embed color per category.
COLORS = {
    MESSAGE: discord.Color.dark_blue(),
    MEMBER: discord.Color.blue(),
    SERVER: discord.Color.dark_teal(),
    MODERATION: discord.Color.red(),
}

# Channels created by /setup_logs.
CHANNEL_NAMES = {
    MESSAGE: "📜-message-logs",
    MEMBER: "👥-member-logs",
    SERVER: "🛠-server-logs",
    MODERATION: "🚨-moderation-logs",
}

LOG_CATEGORY_NAME = "📜 Server Logs"
FOOTER_TEXT = "Kush Bush Logger"


# ----- Per-event toggle keys -----
# Message
EV_MESSAGE_EDIT = "message_edit"
EV_MESSAGE_DELETE = "message_delete"
EV_BULK_DELETE = "bulk_delete"
# Member
EV_MEMBER_JOIN = "member_join"
EV_MEMBER_LEAVE = "member_leave"
EV_MEMBER_KICK = "member_kick"
EV_NICKNAME = "nickname"
EV_AVATAR = "avatar"
EV_ROLE_MEMBER = "role_member"
# Voice
EV_VOICE_JOIN = "voice_join"
EV_VOICE_LEAVE = "voice_leave"
EV_VOICE_MOVE = "voice_move"
EV_VOICE_MUTE = "voice_mute"
# Server
EV_CHANNEL_CREATE = "channel_create"
EV_CHANNEL_DELETE = "channel_delete"
EV_CHANNEL_UPDATE = "channel_update"
EV_THREAD_CREATE = "thread_create"
EV_THREAD_DELETE = "thread_delete"
EV_EMOJI_CREATE = "emoji_create"
EV_EMOJI_DELETE = "emoji_delete"
EV_EMOJI_RENAME = "emoji_rename"
EV_ROLE_CREATE = "role_create"
EV_ROLE_DELETE = "role_delete"
EV_ROLE_UPDATE = "role_update"
EV_INVITE_CREATE = "invite_create"
EV_INVITE_DELETE = "invite_delete"
# Moderation
EV_BAN = "ban"
EV_UNBAN = "unban"
EV_TIMEOUT = "timeout"

# All toggleable events, grouped for /log_toggle and /log_settings.
EVENT_GROUPS = {
    "Message": [EV_MESSAGE_EDIT, EV_MESSAGE_DELETE, EV_BULK_DELETE],
    "Member": [EV_MEMBER_JOIN, EV_MEMBER_LEAVE, EV_MEMBER_KICK,
               EV_NICKNAME, EV_AVATAR, EV_ROLE_MEMBER],
    "Voice": [EV_VOICE_JOIN, EV_VOICE_LEAVE, EV_VOICE_MOVE, EV_VOICE_MUTE],
    "Server": [EV_CHANNEL_CREATE, EV_CHANNEL_DELETE, EV_CHANNEL_UPDATE,
               EV_THREAD_CREATE, EV_THREAD_DELETE,
               EV_EMOJI_CREATE, EV_EMOJI_DELETE, EV_EMOJI_RENAME,
               EV_ROLE_CREATE, EV_ROLE_DELETE, EV_ROLE_UPDATE,
               EV_INVITE_CREATE, EV_INVITE_DELETE],
    "Moderation": [EV_BAN, EV_UNBAN, EV_TIMEOUT],
}

ALL_EVENTS = [e for group in EVENT_GROUPS.values() for e in group]
