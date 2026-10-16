"""Slash commands to configure the Logger."""
import discord
from discord.ext import commands

from  config import GUILD_IDS
from .config import CATEGORIES, CHANNEL_NAMES, LOG_CATEGORY_NAME
from .database import db


class LoggerCommands(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="setup_logs",
        description="Creates logging channels and configures the logger system.",
        guild_ids=GUILD_IDS,
    )
    @commands.has_permissions(administrator=True)
    async def setup_logs(self, ctx):
        await ctx.defer(ephemeral=True)

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=False),
            ctx.guild.me: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_messages=True,
            ),
        }
        for role in ctx.guild.roles:
            if role.permissions.administrator:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    read_message_history=True,
                )

        try:
            category = discord.utils.get(ctx.guild.categories, name=LOG_CATEGORY_NAME)
            if category is None:
                category = await ctx.guild.create_category(
                    LOG_CATEGORY_NAME, overwrites=overwrites
                )

            for log_type in CATEGORIES:
                name = CHANNEL_NAMES[log_type]
                channel = discord.utils.get(category.channels, name=name)
                if channel is None:
                    channel = await ctx.guild.create_text_channel(name, category=category)
                db.set_log_channel(ctx.guild.id, log_type, channel.id)
        except discord.Forbidden:
            await ctx.followup.send(
                "❌ I don't have permission to create channels/categories.",
                ephemeral=True,
            )
            return
        except discord.HTTPException as e:
            await ctx.followup.send(f"❌ Failed to set up log channels: `{e}`", ephemeral=True)
            return

        await ctx.followup.send(
            "✅ Logger channels created and configured.", ephemeral=True
        )

    @discord.slash_command(
        name="change_logchannel",
        description="Point one log category at a different channel.",
        guild_ids=GUILD_IDS,
    )
    async def change_logchannel(
        self,
        ctx,
        log_type: discord.Option(
            str, "Which log category to move",
            choices=CATEGORIES,  # type: ignore
        ),
        channel: discord.Option(discord.TextChannel, "The new log channel"),  # type: ignore
    ):
        if not ctx.author.guild_permissions.administrator:
            await ctx.respond("Administrator permission required.", ephemeral=True)
            return
        db.set_log_channel(ctx.guild.id, log_type, channel.id)
        await ctx.respond(
            embed=discord.Embed(
                title="Logger Updated",
                description=f"**{log_type}** logs will now go to {channel.mention}.",
                color=discord.Color.green(),
            ),
            ephemeral=True,
        )

    @discord.slash_command(
        name="log_settings",
        description="View logger configuration.",
        guild_ids=GUILD_IDS,
    )
    async def log_settings(self, ctx):
        configured = db.get_all_log_channels(ctx.guild.id)
        embed = discord.Embed(title="📜 Logger Settings", color=discord.Color.blurple())
        for log_type in CATEGORIES:
            channel_id = configured.get(log_type)
            channel = ctx.guild.get_channel(channel_id) if channel_id else None
            value = channel.mention if channel else (
                "⚠ Channel deleted" if channel_id else "Not configured"
            )
            embed.add_field(name=log_type.capitalize(), value=value, inline=True)
        await ctx.respond(embed=embed, ephemeral=True)
