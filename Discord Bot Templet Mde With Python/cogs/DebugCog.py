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
# ============================================================

import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup

import os
import time
import traceback
from pathlib import Path

import os
import time

# --- Self-contained debug state (no dependency on web/ package) ---
_FLAG_FILE = Path(__file__).resolve().parent.parent / "data" / ".debug_enabled"
_TRUE_VALUES = {"1", "true", "yes", "on"}


def _debug_enabled():
    try:
        if _FLAG_FILE.exists():
            return _FLAG_FILE.read_text().strip().lower() in _TRUE_VALUES
    except Exception:
        pass
    return os.environ.get("DEBUG", "").lower() in _TRUE_VALUES


def _set_debug(on: bool):
    try:
        _FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _FLAG_FILE.write_text("1" if on else "0")
    except Exception:
        pass
    if on:
        os.environ["DEBUG"] = "1"
    else:
        os.environ.pop("DEBUG", None)


def _dlog(category: str, message: str):
    if not _debug_enabled():
        return
    ts = time.strftime("%H:%M:%S")
    print(f"[DEBUG {ts}][{category}] {message}", flush=True)


def _is_admin(ctx):
    perms = ctx.author.guild_permissions
    return perms.administrator or perms.manage_guild


class DebugCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        if _debug_enabled():
            print("[DEBUG] DebugCog loaded — debug mode is ON", flush=True)

    debug = SlashCommandGroup("debug", "Toggle debug mode")

    @debug.command(name="on", description="Enable debug logging")
    async def debug_on(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        _set_debug(True)
        await ctx.respond("🐛 Debug mode **enabled**.", ephemeral=True)

    @debug.command(name="off", description="Disable debug logging")
    async def debug_off(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        _set_debug(False)
        await ctx.respond("🐛 Debug mode **disabled**.", ephemeral=True)

    @debug.command(name="status", description="Show debug status")
    async def debug_status(self, ctx):
        if not _is_admin(ctx):
            await ctx.respond("You need Manage Server permission.", ephemeral=True)
            return
        on = _debug_enabled()
        await ctx.respond(
            f"🐛 Debug mode is **{'ON' if on else 'OFF'}**.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_application_command(self, ctx):
        if not _debug_enabled():
            return
        cmd_name = ctx.command.qualified_name if ctx.command else "unknown"
        try:
            _dlog(
                "bot",
                f"/{cmd_name} by {ctx.author} "
                f"in #{ctx.channel} ({ctx.guild})",
            )
        except Exception:
            pass

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        cmd_name = ctx.command.qualified_name if ctx.command else "unknown"
        if _debug_enabled():
            ts = time.strftime("%H:%M:%S")
            print(f"[DEBUG {ts}][bot] EXCEPTION (/{cmd_name}): {error}", flush=True)
            traceback.print_exc()
        else:
            print(f"[Bot] Command error in /{cmd_name}: {error}", flush=True)


def setup(bot):
    bot.add_cog(DebugCog(bot))
