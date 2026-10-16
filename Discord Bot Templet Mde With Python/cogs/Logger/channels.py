import discord

from discord.ext import commands

from cogs.Logger.thread_embeds import ThreadEmbeds

from .channel_embeds import ChannelEmbeds

from .base import BaseLogger



class ChannelLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # -----------------------------
    #

    @commands.Cog.listener()

    async def on_guild_channel_create(

        self,

        channel

    ):

        await ChannelEmbeds.created(

            self.bot,

            channel

        )

    #
    # -----------------------------
    #

    @commands.Cog.listener()

    async def on_guild_channel_delete(

        self,

        channel

    ):

        await ChannelEmbeds.deleted(

            self.bot,

            channel

        )

    #
    # -----------------------------
    #

    @commands.Cog.listener()

    async def on_guild_channel_update(

        self,

        before,

        after

    ):

        if before.name != after.name:

            await ChannelEmbeds.renamed(

                self.bot,

                before,

                after

            )

        if isinstance(before, discord.TextChannel) and before.topic != after.topic:

            await ChannelEmbeds.topic(

                self.bot,

                before,

                after

            )

        if before.slowmode_delay != after.slowmode_delay:

            await ChannelEmbeds.slowmode(

                self.bot,

                before,

                after

            )

        if before.nsfw != after.nsfw:

            await ChannelEmbeds.nsfw(

                self.bot,

                before,

                after

            )
    @commands.Cog.listener()
    async def on_thread_create(self, thread):

        await ThreadEmbeds.created(
            self.bot,
            thread
        )


    @commands.Cog.listener()
    async def on_thread_delete(self, thread):

        await ThreadEmbeds.deleted(
            self.bot,
            thread
        )


    @commands.Cog.listener()
    async def on_thread_update(

        self,

        before,

        after

    ):

        if before.archived != after.archived:

            await ThreadEmbeds.archived(

                self.bot,

                before,

                after

            )

        if before.locked != after.locked:

            await ThreadEmbeds.locked(

                self.bot,

                before,

                after

            )