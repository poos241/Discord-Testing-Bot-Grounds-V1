import discord

from discord.ext import commands

from .member_embeds import MemberEmbeds

from .base import BaseLogger



class MemberLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # ------------------------
    #

    @commands.Cog.listener()

    async def on_member_join(self, member):

        await MemberEmbeds.member_join(

            self.bot,

            member

        )

    #
    # ------------------------
    #

    @commands.Cog.listener()

    async def on_member_remove(self, member):

        await MemberEmbeds.member_leave(

            self.bot,

            member

        )

    #
    # ------------------------
    #

    @commands.Cog.listener()

    async def on_member_update(

        self,

        before,

        after

    ):

        #
        # nickname
        #

        if before.nick != after.nick:

            await MemberEmbeds.nickname_change(

                self.bot,

                before,

                after

            )

        #
        # avatar
        #

        if before.display_avatar != after.display_avatar:

            await MemberEmbeds.avatar_change(

                self.bot,

                before,

                after

            )

        #
        # username
        #

        if before.name != after.name:

            await MemberEmbeds.username_change(

                self.bot,

                before,

                after

            )

        #
        # roles
        #

        added = [

            r

            for r in after.roles

            if r not in before.roles

        ]

        removed = [

            r

            for r in before.roles

            if r not in after.roles

        ]

        for role in added:

            await self.role_added(

                after,

                role

            )

        for role in removed:

            await self.role_removed(

                after,

                role

            )

    #
    # ------------------------
    #

    async def role_added(

        self,

        member,

        role

    ):

        embed = discord.Embed(

            title="➕ Role Added",

            color=discord.Color.green(),

            timestamp=discord.utils.utcnow()

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        embed.add_field(

            name="Role",

            value=role.mention

        )

        

        await self.send(

            member.guild,

            "message",

            embed

        )

    #
    # ------------------------
    #

    async def role_removed(

        self,

        member,

        role

    ):

        embed = discord.Embed(

            title="➖ Role Removed",

            color=discord.Color.red(),

            timestamp=discord.utils.utcnow()

        )

        embed.set_author(

            name=str(member),

            icon_url=member.display_avatar.url

        )

        embed.add_field(

            name="Role",

            value=role.mention

        )

        

        await self.send(

            member.guild,

            "message",

            embed
        )