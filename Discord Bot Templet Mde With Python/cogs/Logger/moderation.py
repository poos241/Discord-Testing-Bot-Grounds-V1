import discord

from discord.ext import commands

from .audit import Audit

from .base import BaseLogger

class ModerationLogger(BaseLogger):

    def __init__(self, bot):

        super().__init__(bot)

    #
    # ----------------------------
    #

    @commands.Cog.listener()
    async def on_member_ban(

        self,

        guild,

        user

    ):

        mod = await Audit.executor(

            guild,

            discord.AuditLogAction.ban

        )

        reason = await Audit.reason(

            guild,

            discord.AuditLogAction.ban

        )

        embed = discord.Embed(

            title="🔨 Member Banned",

            color=discord.Color.red(),

            timestamp=discord.utils.utcnow()

        )

        embed.add_field(

            name="User",

            value=str(user),

            inline=False

        )

        embed.add_field(

            name="Moderator",

            value=str(mod) if mod else "Unknown",

            inline=False

        )

        embed.add_field(

            name="Reason",

            value=reason or "None",

            inline=False

        )

        

        await self.send(

            guild,

            "message",

            embed

        )

    #
    # ----------------------------
    #

    @commands.Cog.listener()
    async def on_member_unban(

        self,

        guild,

        user

    ):

        mod = await Audit.executor(

            guild,

            discord.AuditLogAction.unban

        )

        embed = discord.Embed(

            title="♻ Member Unbanned",

            color=discord.Color.green(),

            timestamp=discord.utils.utcnow()

        )

        embed.add_field(

            name="User",

            value=str(user)

        )

        embed.add_field(

            name="Moderator",

            value=str(mod) if mod else "Unknown"

        )

      

        await self.send(

            guild,

            "message",

            embed

        )