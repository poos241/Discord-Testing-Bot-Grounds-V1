from discord.ext import commands

from .sticker_embeds import StickerEmbeds

from .base import BaseLogger



class StickerLogger(BaseLogger):

    def __init__(self, bot):

       super().__init__(bot)

        
    @commands.Cog.listener()
    async def on_guild_stickers_update(

        self,

        guild,

        before,

        after

    ):

        before_map = {

            s.id: s

            for s in before

        }

        after_map = {

            s.id: s

            for s in after

        }

        #
        # Created
        #

        for sticker_id in after_map:

            if sticker_id not in before_map:

                await StickerEmbeds.created(

                    self.bot,

                    after_map[sticker_id]

                )

        #
        # Deleted
        #

        for sticker_id in before_map:

            if sticker_id not in after_map:

                await StickerEmbeds.deleted(

                    self.bot,

                    before_map[sticker_id]

                )

        #
        # Updated
        #

        for sticker_id in before_map:

            if sticker_id not in after_map:

                continue

            old = before_map[sticker_id]

            new = after_map[sticker_id]

            if (

                old.name != new.name

                or

                old.description != new.description

            ):

                await StickerEmbeds.updated(

                    self.bot,

                    old,

                    new

                )