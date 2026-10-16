import discord

from .embeds import LoggerEmbed
from .constants import SERVER


class ServerEmbeds:

    

    @staticmethod
    async def guild_name(bot, before, after):

        embed = LoggerEmbed.base(

            "🏠 Server Renamed",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.name

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.name

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )

    

    @staticmethod
    async def icon(bot, guild):

        embed = LoggerEmbed.base(

            "🖼 Server Icon Updated",

            SERVER

        )

        if guild.icon:

            embed.set_image(

                url=guild.icon.url

            )

        await LoggerEmbed.send(

            bot,

            guild,

            embed

        )

    

    @staticmethod
    async def banner(bot, guild):

        embed = LoggerEmbed.base(

            "🌄 Banner Updated",

            SERVER

        )

        if guild.banner:

            embed.set_image(

                url=guild.banner.url

            )

        await LoggerEmbed.send(

            bot,

            guild,

            embed

        )

    

    @staticmethod
    async def boost(bot, guild):

        embed = LoggerEmbed.base(

            "🚀 Boost Level Changed",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Tier",

            guild.premium_tier

        )

        LoggerEmbed.field(

            embed,

            "Boosts",

            guild.premium_subscription_count

        )

        await LoggerEmbed.send(

            bot,

            guild,

            embed

        )

   

    @staticmethod
    async def verification(bot, before, after):

        embed = LoggerEmbed.base(

            "🛡 Verification Level Changed",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.verification_level

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.verification_level

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )

    

    @staticmethod
    async def afk(bot, before, after):

        embed = LoggerEmbed.base(

            "🎤 AFK Settings Updated",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "AFK Channel",

            after.afk_channel.mention if after.afk_channel else "None"

        )

        LoggerEmbed.field(

            embed,

            "Timeout",

            after.afk_timeout

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )

    

    @staticmethod
    async def system_channel(bot, before, after):

        embed = LoggerEmbed.base(

            "📢 System Channel Updated",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            after.system_channel.mention if after.system_channel else "None"

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )
        


    @staticmethod
    async def description(bot, before, after):

        embed = LoggerEmbed.base(

            "📝 Server Description Changed",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.description

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.description

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )

   

    @staticmethod
    async def vanity(bot, before, after):

        embed = LoggerEmbed.base(

            "🔗 Vanity URL Updated",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Old",

            before.vanity_url_code

        )

        LoggerEmbed.field(

            embed,

            "New",

            after.vanity_url_code

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )

    
    @staticmethod
    async def locale(bot, before, after):

        embed = LoggerEmbed.base(

            "🌎 Preferred Locale Updated",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.preferred_locale

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.preferred_locale

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )



    @staticmethod
    async def afk_channel(bot, before, after):

        embed = LoggerEmbed.base(

            "💤 AFK Channel Changed",

            SERVER

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.afk_channel.mention if before.afk_channel else "None"

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.afk_channel.mention if after.afk_channel else "None"

        )

        await LoggerEmbed.send(

            bot,

            after,

            embed

        )