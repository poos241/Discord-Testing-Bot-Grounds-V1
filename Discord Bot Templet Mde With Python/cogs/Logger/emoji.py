from discord.ext import commands

from .emoji_embeds import EmojiEmbeds

from .base import BaseLogger



class EmojiLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # -------------------------
    #

    @commands.Cog.listener()

    async def on_guild_emojis_update(

        self,

        guild,

        before,

        after

    ):

        before_ids = {

            e.id: e

            for e in before

        }

        after_ids = {

            e.id: e

            for e in after

        }

       
        for emoji_id in after_ids:

            if emoji_id not in before_ids:

                await EmojiEmbeds.created(

                    self.bot,

                    after_ids[emoji_id]

                )

       
        for emoji_id in before_ids:

            if emoji_id not in after_ids:

                await EmojiEmbeds.deleted(

                    self.bot,

                    before_ids[emoji_id]

                )

        

        for emoji_id in before_ids:

            if emoji_id in after_ids:

                old = before_ids[emoji_id]

                new = after_ids[emoji_id]

                if old.name != new.name:

                    await EmojiEmbeds.renamed(

                        self.bot,

                        old,

                        new

                    )