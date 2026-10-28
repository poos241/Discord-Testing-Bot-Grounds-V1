# cogs/AutoThreads.py
"""Auto-threads (built 2026-10-28).

Auto-creates a public discussion thread for messages posted in
designated text channels, with a per-channel archive setting. This
fills the auto_thread gap in config.py: the COMMAND_TAGS entry there
already listed these four command names, but no cog implemented
them, and the legacy threads_settings table was never read by any
code. This cog uses its own table instead of that legacy JSON-blob
table, so each channel's settings are a real row that can be listed
and changed independently.

Commands (all guild-scoped, all require Manage Channels):

  - /auto_thread -- toggle auto-threads for the channel the command
    is run in. Turning it on uses the default 24-hour archive and no
    name prefix; run /set_auto_thread_channel afterwards to tune it.
  - /set_auto_thread_channel <channel> [archive_minutes] [name_prefix]
    -- designate a channel (or update its settings if it is already
    designated). Archive must be one of Discord's allowed values:
    60 (1 hour), 1440 (24 hours, the default), 4320 (3 days), or
    10080 (7 days). The 3-day and 7-day values need a boosted server;
    if Discord rejects one, thread creation falls back to 24 hours
    for that message instead of failing outright.
  - /remove_auto_thread_channel <channel> -- stop auto-threading a
    channel. Existing threads are left alone; only new messages stop
    getting threads.
  - /auto_thread_status -- list every designated channel in this
    server with its archive setting and name prefix.

How a thread is named: the message's own text, collapsed to one line
and cut to 80 characters, optionally prefixed with the channel's
name prefix. Attachment-only messages (no text) get
"<author>'s thread" instead. Names are capped at Discord's 100
characters. The thread is created from the message itself, so the
message becomes the thread's starter message -- no extra bot message
is posted into the thread.

What does NOT get a thread (deliberately):

  - bot and webhook messages, DMs, and anything posted inside a
    thread already (no nested threads);
  - replies -- a reply is already part of a conversation, so
    threading it would just be noise;
  - "!" prefix commands -- a command invocation is not a discussion
    prompt;
  - messages in channels where the bot lacks Create Public Threads
    (skipped silently; the status command still lists the channel,
    so a mod can spot the misconfiguration).

Tables: auto_thread_channels in data/DB/models.py. Storage helpers
live in data/DB/Storage/storage.py. New table only -- create_all()
creates it on the next bot boot and never alters an existing table.
"""
import discord
from discord.ext import commands

from config import GUILD_IDS, Manage_channels_required, extra_help
from data.DB.db import database
from data.DB.Storage.storage import (
    delete_auto_thread_channel,
    get_auto_thread_channel,
    list_auto_thread_channels,
    save_auto_thread_channel,
)

# Discord's only allowed auto-archive durations, in minutes.
ARCHIVE_CHOICES = (60, 1440, 4320, 10080)
DEFAULT_ARCHIVE_MINUTES = 1440
# Thread names are capped at 100 characters by Discord.
MAX_THREAD_NAME = 100
MAX_CONTENT_IN_NAME = 80
MAX_NAME_PREFIX = 40


def _archive_label(minutes):
    labels = {60: "1 hour", 1440: "24 hours", 4320: "3 days",
              10080: "7 days"}
    return labels.get(minutes, f"{minutes} minutes")


def _thread_name(message, prefix):
    """Thread name for a message: optional prefix + message text.

    Text is collapsed to one line (newlines become spaces) and cut
    to 80 characters; attachment-only messages fall back to the
    author's name. The result is capped at Discord's 100 chars.
    """
    content = " ".join((message.content or "").split())
    if content:
        base = content[:MAX_CONTENT_IN_NAME]
    else:
        base = f"{message.author.display_name}'s thread"
    if prefix:
        name = f"{prefix} {base}"
    else:
        name = base
    name = name[:MAX_THREAD_NAME].rstrip()
    return name or f"{message.author.display_name}'s thread"


class AutoThreads(commands.Cog):
    """Auto-create discussion threads for designated channels."""

    def __init__(self, bot):
        self.bot = bot

    # ---------- internals ----------

    async def _ensure_db(self):
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[AutoThreads] DB connect check failed: {e!r}")

    def _should_thread(self, message):
        """True when this message should get an auto-thread."""
        if message.guild is None or message.author.bot:
            return False
        if getattr(message, "webhook_id", None) is not None:
            return False
        # Inside a thread already, or not a plain text channel at all
        # (forum posts arrive as threads; DMs have no guild anyway).
        if isinstance(message.channel, discord.Thread):
            return False
        if not isinstance(message.channel, discord.TextChannel):
            return False
        # Replies are already part of a conversation; "!" lines are
        # bot commands, not discussion prompts.
        if message.reference is not None:
            return False
        if (message.content or "").startswith("!"):
            return False
        # The bot needs Create Public Threads in this channel; if it
        # does not have it, creating would just raise Forbidden.
        try:
            perms = message.channel.permissions_for(message.guild.me)
            if not perms.create_public_threads:
                return False
        except Exception:
            return False
        return True

    async def _create_thread(self, message, archive_minutes):
        """Create the thread, falling back to 24h archive if Discord
        rejects the configured duration (e.g. 3/7 days on an
        unboosted server). Never raises."""
        name = None
        try:
            cfg = await get_auto_thread_channel(
                str(message.guild.id), str(message.channel.id))
            name = _thread_name(message, (cfg.get("name_prefix") or ""))
        except Exception as e:
            print(f"[AutoThreads] Config read failed: {e!r}")
            return
        if not cfg:
            return
        try:
            await message.create_thread(
                name=name, auto_archive_duration=int(archive_minutes))
        except discord.HTTPException:
            if int(archive_minutes) != DEFAULT_ARCHIVE_MINUTES:
                try:
                    await message.create_thread(
                        name=name,
                        auto_archive_duration=DEFAULT_ARCHIVE_MINUTES)
                    return
                except discord.DiscordException as e:
                    print(f"[AutoThreads] Thread create failed (fallback) "
                          f"in #{message.channel.name}: {e!r}")
            else:
                print(f"[AutoThreads] Thread create failed "
                      f"in #{message.channel.name}: "
                      f"archive={archive_minutes} (check bot permissions)")
        except discord.DiscordException as e:
            print(f"[AutoThreads] Thread create failed "
                  f"in #{message.channel.name}: {e!r}")

    # ---------- message listener ----------

    @commands.Cog.listener()
    async def on_message(self, message):
        if not self._should_thread(message):
            return
        await self._ensure_db()
        try:
            cfg = await get_auto_thread_channel(
                str(message.guild.id), str(message.channel.id))
        except Exception as e:
            print(f"[AutoThreads] Config read failed: {e!r}")
            return
        if not cfg:
            return
        await self._create_thread(
            message, int(cfg.get("archive_minutes") or DEFAULT_ARCHIVE_MINUTES))

    # ---------- commands ----------

    @discord.slash_command(name="auto_thread",
                           description="Toggle auto-threads for the channel this command is run in.",
                           guild_ids=GUILD_IDS)
    @extra_help("No arguments: flips auto-threads on or off for the current channel. Turning it on uses the default 24-hour archive and no name prefix; use /set_auto_thread_channel to tune the archive time or add a name prefix. Requires Manage Channels. Does not work in threads or DMs.")
    @Manage_channels_required()
    async def auto_thread_toggle(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Auto-thread commands only work in a server.",
                                     ephemeral=True)
        if not isinstance(ctx.channel, discord.TextChannel):
            return await ctx.respond(
                "Run this in a text channel, not in a thread or DM.",
                ephemeral=True)
        await self._ensure_db()
        existing = await get_auto_thread_channel(
            str(ctx.guild.id), str(ctx.channel.id))
        if existing:
            await delete_auto_thread_channel(
                str(ctx.guild.id), str(ctx.channel.id))
            return await ctx.respond(
                f"Auto-threads are now **off** for {ctx.channel.mention}. "
                "Existing threads are left alone.",
                ephemeral=True)
        await save_auto_thread_channel(
            str(ctx.guild.id), str(ctx.channel.id),
            {"archive_minutes": DEFAULT_ARCHIVE_MINUTES, "name_prefix": ""})
        await ctx.respond(
            f"Auto-threads are now **on** for {ctx.channel.mention}: every "
            f"new message gets a discussion thread that auto-archives "
            f"after {_archive_label(DEFAULT_ARCHIVE_MINUTES)}. Tune it with "
            "/set_auto_thread_channel.",
            ephemeral=True)

    @discord.slash_command(name="set_auto_thread_channel",
                           description="Designate a channel for auto-threads, or update its settings.",
                           guild_ids=GUILD_IDS)
    @extra_help("Channel: the text channel to designate. Archive minutes: 60, 1440, 4320, or 10080 (blank keeps the current setting, or 24 hours for a new channel). Name prefix: optional text put in front of every thread name in this channel, e.g. 'Discussion' (blank keeps the current prefix, or none for a new channel). Requires Manage Channels.")
    @Manage_channels_required()
    async def set_auto_thread_channel_cmd(
            self, ctx,
            channel: discord.Option(discord.TextChannel, "Text channel to designate for auto-threads"),
            archive_minutes: discord.Option(int, "Auto-archive after: 60, 1440, 4320, or 10080 minutes (blank keeps current)", required=False, default=None),
            name_prefix: discord.Option(str, "Optional text put in front of every thread name (blank keeps current)", required=False, default=None)):
        if ctx.guild is None:
            return await ctx.respond("Auto-thread commands only work in a server.",
                                     ephemeral=True)
        await self._ensure_db()
        existing = await get_auto_thread_channel(
            str(ctx.guild.id), str(channel.id))
        payload = {
            "archive_minutes": existing.get("archive_minutes") or DEFAULT_ARCHIVE_MINUTES,
            "name_prefix": existing.get("name_prefix") or "",
        }
        if archive_minutes is not None:
            if int(archive_minutes) not in ARCHIVE_CHOICES:
                return await ctx.respond(
                    "Archive must be one of Discord's allowed values: "
                    "60 (1 hour), 1440 (24 hours), 4320 (3 days), "
                    "or 10080 (7 days).",
                    ephemeral=True)
            payload["archive_minutes"] = int(archive_minutes)
        if name_prefix is not None:
            payload["name_prefix"] = name_prefix.strip()[:MAX_NAME_PREFIX]
        await save_auto_thread_channel(
            str(ctx.guild.id), str(channel.id), payload)
        verb = "updated" if existing else "designated"
        await ctx.respond(
            f"{channel.mention} {verb} for auto-threads: threads "
            f"auto-archive after {_archive_label(payload['archive_minutes'])}"
            + (f", thread names start with **{payload['name_prefix']}**."
               if payload["name_prefix"] else "."),
            ephemeral=True)

    @discord.slash_command(name="remove_auto_thread_channel",
                           description="Stop auto-threading a channel (existing threads are left alone).",
                           guild_ids=GUILD_IDS)
    @extra_help("Removes the channel from the auto-thread list. New messages stop getting threads; threads already created stay where they are. Requires Manage Channels.")
    @Manage_channels_required()
    async def remove_auto_thread_channel_cmd(
            self, ctx,
            channel: discord.Option(discord.TextChannel, "Text channel to stop auto-threading")):
        if ctx.guild is None:
            return await ctx.respond("Auto-thread commands only work in a server.",
                                     ephemeral=True)
        await self._ensure_db()
        existing = await get_auto_thread_channel(
            str(ctx.guild.id), str(channel.id))
        if not existing:
            return await ctx.respond(
                f"{channel.mention} is not designated for auto-threads.",
                ephemeral=True)
        await delete_auto_thread_channel(
            str(ctx.guild.id), str(channel.id))
        await ctx.respond(
            f"Auto-threads are now **off** for {channel.mention}. "
            "Existing threads are left alone.",
            ephemeral=True)

    @discord.slash_command(name="auto_thread_status",
                           description="List every channel designated for auto-threads in this server.",
                           guild_ids=GUILD_IDS)
    @extra_help("Read-only list of designated channels with each one's archive setting and name prefix. Requires Manage Channels.")
    @Manage_channels_required()
    async def auto_thread_status_cmd(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Auto-thread commands only work in a server.",
                                     ephemeral=True)
        await self._ensure_db()
        rows = await list_auto_thread_channels(str(ctx.guild.id))
        if not rows:
            return await ctx.respond(
                "No channels are designated for auto-threads yet. Use "
                "/set_auto_thread_channel to add one, or run /auto_thread "
                "in a channel to toggle it on there.",
                ephemeral=True)
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            name = channel.mention if channel else f"(deleted channel `{row['channel_id']}`)"
            prefix = row.get("name_prefix") or ""
            lines.append(
                f"{name}: archives after "
                f"{_archive_label(int(row.get('archive_minutes') or DEFAULT_ARCHIVE_MINUTES))}"
                + (f", thread names start with **{prefix}**" if prefix else ""))
        embed = discord.Embed(
            title="Auto-thread Channels", color=discord.Color.blurple(),
            description="\n".join(lines[:25]))
        if len(lines) > 25:
            embed.set_footer(text=f"And {len(lines) - 25} more designated channels.")
        await ctx.respond(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(AutoThreads(bot))
