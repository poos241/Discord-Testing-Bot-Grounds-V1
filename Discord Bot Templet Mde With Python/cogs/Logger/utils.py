from .database import database


def set_log_channel(guild_id, log_type, channel_id):

    database.set_log_channel(guild_id, log_type, channel_id)


def get_log_channel(guild_id, log_type):

    return database.get_log_channel(guild_id, log_type)


async def send_log(bot, guild_id, log_type, embed):

    channel_id = get_log_channel(guild_id, log_type)

    if not channel_id:
        return

    channel = bot.get_channel(channel_id)

    if not channel:
        return

    await channel.send(embed=embed)