from discord.ext import commands

from .role_embeds import RoleEmbeds

from .base import BaseLogger

class RoleLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_guild_role_create(

        self,

        role

    ):

        await RoleEmbeds.created(

            self.bot,

            role.guild,

            role

        )

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_guild_role_delete(

        self,

        role

    ):

        await RoleEmbeds.deleted(

            self.bot,

            role.guild,

            role

        )

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_guild_role_update(

        self,

        before,

        after

    ):

        if before.name != after.name:

            await RoleEmbeds.updated(

                self.bot,

                after.guild,

                before,

                after

            )