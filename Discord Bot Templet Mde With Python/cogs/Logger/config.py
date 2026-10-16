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
