import discord

from discord.ext import commands

from .voice_cache import voice_cache

from .voice_embeds import VoiceEmbeds

from .base import BaseLogger

class VoiceLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # --------------------------------
    #

    @commands.Cog.listener()

    async def on_voice_state_update(

        self,

        member,

        before,

        after

    ):

        #
        # joined
        #

        if before.channel is None and after.channel:

            voice_cache.update(

                member,

                after.channel

            )

            await VoiceEmbeds.joined(

                self.bot,

                member,

                after.channel

            )

            return

        #
        # left
        #

        if before.channel and after.channel is None:

            voice_cache.remove(

                member

            )

            await VoiceEmbeds.left(

                self.bot,

                member,

                before.channel

            )

            return

        #
        # moved
        #

        if before.channel != after.channel:

            voice_cache.update(

                member,

                after.channel

            )

            await VoiceEmbeds.moved(

                self.bot,

                member,

                before.channel,

                after.channel

            )

        #
        # mute
        #

        if before.self_mute != after.self_mute:

            await self.self_mute(

                member,

                after.self_mute

            )

        #
        # deaf
        #

        if before.self_deaf != after.self_deaf:

            await self.self_deaf(

                member,

                after.self_deaf

            )

        #
        # stream
        #

        if before.self_stream != after.self_stream:

            await self.stream(

                member,

                after.self_stream

            )

        #
        # camera
        #

        if before.self_video != after.self_video:

            await self.camera(

                member,

                after.self_video

            )

        #
        # server mute
        #

        if before.mute != after.mute:

            await self.server_mute(

                member,

                after.mute

            )

        #
        # server deaf
        #

        if before.deaf != after.deaf:

            await self.server_deaf(

                member,

                after.deaf

            )

    #
    # --------------------------------
    #

    async def self_mute(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="🎤 Self Mute",

            color=discord.Color.orange(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Enabled"

            if enabled

            else

            "Disabled"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

            member.guild,

            "member",

            embed

        )

    #
    # --------------------------------
    #

    async def self_deaf(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="🎧 Self Deaf",

            color=discord.Color.orange(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Enabled"

            if enabled

            else

            "Disabled"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

            member.guild,

            "member",

            embed

        )

    #
    # --------------------------------
    #

    async def stream(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="📺 Streaming",

            color=discord.Color.purple(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Started Streaming"

            if enabled

            else

            "Stopped Streaming"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

            member.guild,

            "member",

            embed

        )

    #
    # --------------------------------
    #

    async def camera(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="📷 Camera",

            color=discord.Color.blurple(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Camera Enabled"

            if enabled

            else

            "Camera Disabled"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

           member.guild,

            "member",

            embed

        )

    #
    # --------------------------------
    #

    async def server_mute(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="🔇 Server Mute",

            color=discord.Color.red(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Muted"

            if enabled

            else

            "Unmuted"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

            member.guild,

            "member",

            embed

        )

    #
    # --------------------------------
    #

    async def server_deaf(

        self,

        member,

        enabled

    ):

        

        embed = discord.Embed(

            title="🔈 Server Deaf",

            color=discord.Color.red(),

            timestamp=discord.utils.utcnow()

        )

        embed.description = (

            "Deafened"

            if enabled

            else

            "Undeafened"

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        await self.send(

            member.guild,

            "member",

            embed

        )