import discord
from discord.ext import commands
import asyncio

from config import GUILD_IDS

# Fixed the mismatch here: making sure we use set_log_channel
from .utils import (
    set_log_channel,
    get_log_channel,
    send_log
)


class LoggerCommands(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.cooldowns = {}

    # --------------------------------------------------------

    @discord.slash_command(name="setup_logs",description="Creates logging channels and configures the logger system.",guild_ids=GUILD_IDS)
    @commands.has_permissions(administrator=True) 
    async def setup_logs(self, ctx):
        await ctx.defer(ephemeral=True)

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(
                view_channel=False
            ),
            ctx.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True
            )
        }

        for role in ctx.guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True
                )

        category = discord.utils.get(
            ctx.guild.categories,
            name="📜 Server Logs"
        )

        if category is None:
            category = await ctx.guild.create_category(
                "📜 Server Logs",
                overwrites=overwrites
            )


        channels = {
            "message": "📜-message-logs",
            "member": "👥-member-logs",
            "server": "🛠-server-logs",
            "moderation": "🚨-moderation-logs"
        }

        for key, name in channels.items():
            channel = discord.utils.get(
                category.channels,
                name=name
            )

          
            if channel is None:
                channel = await ctx.guild.create_text_channel(
                    name,
                    category=category
                )
            
            
            set_log_channel(
                ctx.guild.id,
                key,
                channel.id
            )

        await ctx.followup.send(
            "✅ Logger and permission overwrites configured successfully.", 
            ephemeral=True
        )



    @discord.slash_command(name="change_logchannel",description="Choose another log channel.",guild_ids=GUILD_IDS)
    async def change_logchannel(

        self,

        ctx,

        channel: discord.Option(discord.TextChannel) # type: ignore

    ):

        if not ctx.author.guild_permissions.administrator:

            return await ctx.respond(

                "Administrator permission required.",

                ephemeral=True

            )

        set_log_channel(

            ctx.guild.id,

            channel.id

        )

        embed = discord.Embed(

            title="Logger Updated",

            description=f"New log channel: {channel.mention}",

            color=discord.Color.green()

        )

        await ctx.respond(embed=embed)

    #
    # --------------------------------------------------------
    #

    @discord.slash_command( name="log_settings",description="View logger configuration.",guild_ids=GUILD_IDS)
    async def log_settings(

        self,

        ctx

    ):

        channel_id = get_log_channel(

            ctx.guild.id

        )

        embed = discord.Embed(

            title="Logger Settings",

            color=discord.Color.blurple()

        )

        if channel_id:

            channel = ctx.guild.get_channel(

                channel_id

            )

            embed.add_field(

                name="Current Channel",

                value=channel.mention if channel else "Missing"

            )

        else:

            embed.add_field(

                name="Current Channel",

                value="Not Configured"

            )

        embed.add_field(

            name="Message Logs",

            value="Enabled"

        )

        embed.add_field(

            name="Voice Logs",

            value="Enabled"

        )

        embed.add_field(

            name="Member Logs",

            value="Enabled"

        )

        embed.add_field(

            name="Role Logs",

            value="Enabled"

        )

        embed.add_field(

            name="Channel Logs",

            value="Enabled"

        )

        await ctx.respond(embed=embed)


def setup(bot):

    bot.add_cog(

        LoggerCommands(bot)

    )