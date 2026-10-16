import discord

from discord.ext import commands

from .cache import cache

from .database import database

from .message_embeds import MessageEmbeds

from .base import BaseLogger



class MessageLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_message(self, message):

        if message.author.bot:

            return

        if not message.guild:

            return

        cache.add(message)

        database.save(message)

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_message_delete(self, message):

        if message.author.bot:

            return

        await MessageEmbeds.deleted(

            self.bot,

            message

        )

        cache.remove(

            message.id

        )

        database.delete(

            message.id

        )

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_message_edit(

        self,

        before,

        after

    ):

        if before.author.bot:

            return

        if before.content == after.content:

            return

        await MessageEmbeds.edited(

            self.bot,

            before,

            after

        )

        cache.add(after)

        database.save(after)