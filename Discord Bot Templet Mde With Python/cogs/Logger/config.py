MESSAGE = "message"

MEMBER = "member"

SERVER = "server"

MODERATION = "moderation"

LOG_TYPES = {

    "message_create": MESSAGE,

    "message_edit": MESSAGE,

    "message_delete": MESSAGE,

    "bulk_delete": MESSAGE,

    "member_join": MEMBER,

    "member_leave": MEMBER,

    "voice_join": MEMBER,

    "voice_leave": MEMBER,

    "voice_move": MEMBER,

    "ban": MODERATION,

    "kick": MODERATION,

    "timeout": MODERATION,

    "role_create": SERVER,

    "role_delete": SERVER,

    "channel_create": SERVER,

    "emoji_create": SERVER,

    "sticker_create": SERVER,

    "guild_update": SERVER

}