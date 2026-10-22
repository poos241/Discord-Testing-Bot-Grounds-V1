# ============================================================
# DebugCog — runtime debug toggle for the Discord bot
#
# Commands (admin only):
#   /debug on      — enable verbose debug logging
#   /debug off     — disable debug logging
#   /debug status  — show current debug state
#
# Toggle via env var at startup:  DEBUG=1
# Toggle at runtime: /debug on|off  (persists via data/.debug_enabled)
#
# When enabled, the bot logs:
#   - every slash command invocation (user, guild, options)
#   - full tracebacks on command errors
#   - cog load/unload events
# ============================================================

import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup, Option

import os
import sys
import time
import traceback
from pathlib import Path


# Add web/ to path so we can use the shared debug module
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "web"))
try:
    from web import debug as dbg
except ImportError:
    dbg = None


def _is_admin(ctx):
    perms = ctx.author.guild_permissions
    return perms.administrator or perms.manage_guild


class DebugCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if dbg and dbg.is_enabled():
            print("[DEBUG] DebugCog loaded — debug mode is ON")

    debug = SlashCommandGroup("debug", "Toggle debug mode")

    @debug.command(name="on", description="Enable debug logging")
    async def debug_on(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        if dbg:
            dbg.set_enabled(True)
        os.environ["DEBUG"] = "1"
        await ctx.respond("🐛 Debug mode **enabled**.", ephemeral=True)

    @debug.command(name="off", description="Disable debug logging")
    async def debug_off(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        if dbg:
            dbg.set_enabled(False)
        os.environ.pop("DEBUG", None)
        await ctx.respond("🐛 Debug mode **disabled**.", ephemeral=True)

    @debug.command(name="status", description="Show debug status")
    async def debug_status(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        on = dbg.is_enabled() if dbg else os.environ.get("DEBUG") == "1"
        await ctx.respond(
            f"🐛 Debug mode is **{'ON' if on else 'OFF'}**.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_application_command(self, ctx):
        if dbg and dbg.is_enabled():
            opts = ""
            try:
                opts = str(ctx.selected_options) if hasattr(ctx, "selected_options") else ""
            except Exception:
                pass
            dbg.log(
                "bot",
                f"/{ctx.command.qualified_name} by {ctx.author} "
                f"in #{ctx.channel} ({ctx.guild}) {opts}",
            )

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        if dbg and dbg.is_enabled():
            dbg.log_exception("bot", error, f"/{ctx.command}")
        # Also log the basics even when debug is off
        print(f"[Bot] Command error in /{ctx.command}: {error}", flush=True)


def setup(bot):
    bot.add_cog(DebugCog(bot))
