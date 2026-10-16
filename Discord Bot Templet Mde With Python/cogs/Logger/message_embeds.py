import discord

from cogs.Logger.utils import send_log

from .embeds import LoggerEmbed

from .constants import MESSAGE


class MessageEmbeds:

    @staticmethod
    async def deleted(bot, message):

        embed = LoggerEmbed.base(

            "🗑 Message Deleted",

            MESSAGE

        )

        LoggerEmbed.author(

            embed,

            message.author

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            message.channel.mention,

            True
        )

        LoggerEmbed.field(

            embed,

            "Content",

            message.content or "*No message content.*"

        )
        
        LoggerEmbed.field(

            embed,

            "Created",

            discord.utils.format_dt(

                message.created_at,

                style="F"

            ),

            False

        )

        if message.attachments:

            attachment_text = []

            for attachment in message.attachments:

                attachment_text.append(

                    f"📎 [{attachment.filename}]({attachment.url})"

                )

            LoggerEmbed.field(

                embed,

                "Attachments",

                "\n".join(attachment_text)

            )

            first = message.attachments[0]

            if first.content_type:

                if first.content_type.startswith("image"):

                    embed.set_image(

                        url=first.url

                    )
        if message.reference:

            LoggerEmbed.field(

                embed,

                "Replying To",

                str(message.reference.message_id)

            )
            
        if message.stickers:

            stickers = []

            for sticker in message.stickers:

                stickers.append(sticker.name)

            LoggerEmbed.field(

                embed,

                "Stickers",

                "\n".join(stickers)

            )
            
            
        for attachment in message.attachments:

            if attachment.content_type:

                if attachment.content_type.startswith("image"):

                    embed.set_image(

                        url=attachment.url

                    )

                    break
                
        await send_log(bot, message.guild.id, "message", embed=embed)

    @staticmethod
    async def edited(bot, before, after):

        embed = LoggerEmbed.base(

            "✏ Message Edited",

            MESSAGE

        )

        LoggerEmbed.author(

            embed,

            before.author

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            before.channel.mention

        )

        LoggerEmbed.field(

            embed,

            "Before",

            before.content or "*Empty*"

        )

        LoggerEmbed.field(

            embed,

            "After",

            after.content or "*Empty*"

        )

        await send_log(bot, before.guild.id, "message", embed=embed)
        

    @staticmethod
    async def sent(bot, message):

        embed = LoggerEmbed.base(

            "📨 Message Cached",

            MESSAGE

        )

        LoggerEmbed.author(

            embed,

            message.author

        )

        LoggerEmbed.field(

            embed,

            "Channel",

            message.channel.mention

        )

        LoggerEmbed.field(

            embed,

            "Message",

            message.content

        )

        await LoggerEmbed.send(

            bot,

            message.guild,

            embed
        )