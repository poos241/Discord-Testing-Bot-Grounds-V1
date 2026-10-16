from discord.ext import commands

from .server_embeds import ServerEmbeds

from .base import BaseLogger

class ServerLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # --------------------------------------
    #

    @commands.Cog.listener()

    async def on_guild_update(

        self,

        before,

        after

    ):

        #
        # name
        #

        if before.name != after.name:

            await ServerEmbeds.guild_name(

                self.bot,

                before,

                after

            )

        #
        # icon
        #

        if before.icon != after.icon:

            await ServerEmbeds.icon(

                self.bot,

                after

            )

        #
        # banner
        #

        if before.banner != after.banner:

            await ServerEmbeds.banner(

                self.bot,

                after

            )

        #
        # boosts
        #

        if (

            before.premium_tier

            !=

            after.premium_tier

            or

            before.premium_subscription_count

            !=

            after.premium_subscription_count

        ):

            await ServerEmbeds.boost(

                self.bot,

                after

            )

        #
        # verification
        #

        if (

            before.verification_level

            !=

            after.verification_level

        ):

            await ServerEmbeds.verification(

                self.bot,

                before,

                after

            )

        #
        # afk
        #

        if (

            before.afk_channel

            !=

            after.afk_channel

            or

            before.afk_timeout

            !=

            after.afk_timeout

        ):

            await ServerEmbeds.afk(

                self.bot,

                before,

                after

            )

        #
        # system channel
        #

        if (

            before.system_channel

            !=

            after.system_channel

        ):

            await ServerEmbeds.system_channel(

                self.bot,

                before,

                after

            )
        #
        # Description
        #

        if before.description != after.description:

            await ServerEmbeds.description(

                self.bot,

                before,

                after

            )

        #
        # Vanity URL
        #

        if before.vanity_url_code != after.vanity_url_code:

            await ServerEmbeds.vanity(

                self.bot,

                before,

                after

            )

        #
        # Locale
        #

        if before.preferred_locale != after.preferred_locale:

            await ServerEmbeds.locale(

                self.bot,

                before,

                after

            )

        #
        # AFK Channel
        #

        if before.afk_channel != after.afk_channel:

            await ServerEmbeds.afk_channel(

                self.bot,

                before,

                after

            )    
            
            
    @commands.Cog.listener()
    async def on_invite_create(

        self,

        invite

    ):

        from .invite_embeds import InviteEmbeds

        await InviteEmbeds.created(

            self.bot,

            invite

        )


    @commands.Cog.listener()
    async def on_invite_delete(

        self,

        invite

    ):

        from .invite_embeds import InviteEmbeds

        await InviteEmbeds.deleted(

            self.bot,

            invite

        )