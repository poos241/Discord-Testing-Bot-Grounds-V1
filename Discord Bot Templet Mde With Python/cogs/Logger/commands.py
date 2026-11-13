"""Slash commands to configure the Logger."""
import asyncio

import discord
from discord.ext import commands, tasks
from discord.commands import SlashCommandGroup

from config import GUILD_IDS, WORKER_MODE
from .config import (MESSAGE, MEMBER, SERVER, MODERATION,
    CATEGORIES, CHANNEL_NAMES, LOG_CATEGORY_NAME, ALL_EVENTS, EVENT_GROUPS)
from .database import db


def _log_channel_usable(channel, member):
    """(ok, reason) -- can the bot see this channel and send in it?

    A log channel the bot cannot send in fails silently later
    (Logger.send swallows the failure), so this is checked at set
    time, the same way Introduction checks its log channel.
    """
    if channel is None or member is None:
        return False, "not found"
    try:
        perms = channel.permissions_for(member)
    except Exception:
        return False, "could not check its permissions"
    if not getattr(perms, "view_channel", True):
        return False, "the bot cannot see it"
    if not getattr(perms, "send_messages", False):
        return False, "the bot cannot send messages there"
    return True, ""


# /log_toggle as a group: Discord caps option choices at 25, and we have 29
# events, so they're split into per-category subcommands. (Module-level:
# pycord drops choices on group subcommands defined as cog methods.)
log_toggle_group = discord.SlashCommandGroup(
    "log_toggle",
    "Enable or disable logging for a specific event type.",
    guild_ids=GUILD_IDS,
)


async def _do_log_toggle(ctx, event, enabled, command):
    # ``command`` is this subcommand's grantable key (log_toggle_message
    # etc.). check_slash_permission also covers the DM case: in a DM
    # ctx.author is a discord.User, so has_command_permission returns
    # False and the denial is sent (P3-1, formerly an inline guard).
    from utils.permissions import check_slash_permission, _default_admin_only
    if not await check_slash_permission(ctx, command, _default_admin_only):
        return
    db.set_enabled(ctx.guild.id, event, enabled)
    state = "enabled \u2705" if enabled else "disabled \u274c"
    await ctx.respond(f"Logging for `{event}` is now {state}.", ephemeral=True)


@log_toggle_group.command(name="message", description="Toggle message event logging.")
async def toggle_message(
    ctx,
    event: discord.Option(str, "Event type", choices=[
        "message_edit", "message_delete", "bulk_delete"]),  # type: ignore
    enabled: discord.Option(bool, "Turn this event on or off"),  # type: ignore
):
    await _do_log_toggle(ctx, event, enabled, "log_toggle_message")


@log_toggle_group.command(name="member", description="Toggle member event logging.")
async def toggle_member(
    ctx,
    event: discord.Option(str, "Event type", choices=[
        "member_join", "member_leave", "member_kick",
        "nickname", "avatar", "role_member"]),  # type: ignore
    enabled: discord.Option(bool, "Turn this event on or off"),  # type: ignore
):
    await _do_log_toggle(ctx, event, enabled, "log_toggle_member")


@log_toggle_group.command(name="voice", description="Toggle voice event logging.")
async def toggle_voice(
    ctx,
    event: discord.Option(str, "Event type", choices=[
        "voice_join", "voice_leave", "voice_move", "voice_mute"]),  # type: ignore
    enabled: discord.Option(bool, "Turn this event on or off"),  # type: ignore
):
    await _do_log_toggle(ctx, event, enabled, "log_toggle_voice")


@log_toggle_group.command(name="server", description="Toggle server event logging.")
async def toggle_server(
    ctx,
    event: discord.Option(str, "Event type", choices=[
        "channel_create", "channel_delete", "channel_update",
        "thread_create", "thread_delete",
        "emoji_create", "emoji_delete", "emoji_rename",
        "role_create", "role_delete", "role_update",
        "invite_create", "invite_delete"]),  # type: ignore
    enabled: discord.Option(bool, "Turn this event on or off"),  # type: ignore
):
    await _do_log_toggle(ctx, event, enabled, "log_toggle_server")


@log_toggle_group.command(name="moderation", description="Toggle moderation event logging.")
async def toggle_moderation(
    ctx,
    event: discord.Option(str, "Event type", choices=[
        "ban", "unban", "timeout"]),  # type: ignore
    enabled: discord.Option(bool, "Turn this event on or off"),  # type: ignore
):
    await _do_log_toggle(ctx, event, enabled, "log_toggle_moderation")


class LoggerCommands(commands.Cog):
    if WORKER_MODE:
        logs = SlashCommandGroup("logs", "Server log channels and settings.", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        # The event-history prune is a background job: it runs ONLY on
        # the main bot. The worker loads this cog for its /logs +
        # /log_toggle commands, but the prune is a DELETE sweep -- one
        # runner is enough, and the main bot is the one that owns the
        # Logger's listeners.
        if not WORKER_MODE:
            self._prune_event_history.start()

    def cog_unload(self):
        self._prune_event_history.cancel()

    @tasks.loop(minutes=30)
    async def _prune_event_history(self):
        """Periodic event-history retention sweep (P1-25).

        The per-event prune DELETE used to run inside every
        Logger.send(), scanning the events table on the gateway loop.
        record_event() now inserts only; this sweep trims each guild
        back to the newest 5000 rows every 30 minutes, in a worker
        thread. A failed sweep only logs -- the next tick retries.
        """
        try:
            deleted = await asyncio.to_thread(db.prune_events)
        except Exception as e:
            print(f"[LOGGER] ERROR: event-history prune failed: {e!r}; will retry next sweep")
            return
        if deleted:
            print(f"[LOGGER] Pruned {deleted} old event rows")

    @_prune_event_history.before_loop
    async def _before_prune_event_history(self):
        await self.bot.wait_until_ready()

    if WORKER_MODE:
        @logs.command(
            name="setup",
            description="Creates logging channels and configures the logger system.",
        )
        async def setup_logs(
            self,
            ctx,
            message_channel: discord.Option(
                discord.TextChannel,
                "Use this existing channel for message logs instead of creating one",
                required=False, default=None),  # type: ignore
            member_channel: discord.Option(
                discord.TextChannel,
                "Use this existing channel for member logs instead of creating one",
                required=False, default=None),  # type: ignore
            server_channel: discord.Option(
                discord.TextChannel,
                "Use this existing channel for server logs instead of creating one",
                required=False, default=None),  # type: ignore
            moderation_channel: discord.Option(
                discord.TextChannel,
                "Use this existing channel for moderation logs instead of creating one",
                required=False, default=None),  # type: ignore
            create_channels: discord.Option(
                bool,
                "Create the log category and any missing channels instead of skipping them",
                required=False, default=False),  # type: ignore
        ):
            from utils.permissions import check_slash_permission, _default_admin_only
            if not await check_slash_permission(
                    ctx, "logs_setup", _default_admin_only):
                return
            await ctx.defer(ephemeral=True)

            # A channel given here is bound as-is (it may live outside the
            # log category); a category left blank is only created when
            # create_channels is on. Otherwise it is skipped entirely --
            # it stays unconfigured until a channel is passed for it, or
            # create_channels is turned on.
            custom = {
                MESSAGE: message_channel,
                MEMBER: member_channel,
                SERVER: server_channel,
                MODERATION: moderation_channel,
            }
            if not create_channels and not any(custom.values()):
                await ctx.followup.send(
                    "Nothing was set up — pass a channel for a category, or "
                    "turn on **create_channels** to create the log category "
                    "and any missing channels.",
                    ephemeral=True,
                )
                return
            # Validate the custom channels before creating anything: a
            # channel the bot cannot send in fails silently later.
            me = ctx.guild.me
            for log_type, channel in custom.items():
                if channel is None:
                    continue
                ok, why = _log_channel_usable(channel, me)
                if not ok:
                    await ctx.followup.send(
                        f"I can't use {channel.mention} for **{log_type}** "
                        f"logs: {why}.",
                        ephemeral=True,
                    )
                    return

            # The log category is only needed when a channel is actually
            # being created below, so it is never created just for binding
            # passed channels.
            need_create = create_channels and any(
                c is None for c in custom.values()
            )
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
                category = None
                if need_create:
                    category = discord.utils.get(ctx.guild.categories, name=LOG_CATEGORY_NAME)
                    if category is None:
                        category = await ctx.guild.create_category(
                            LOG_CATEGORY_NAME, overwrites=overwrites
                        )

                bound = []
                created = []
                reused = []
                skipped = []
                for log_type in CATEGORIES:
                    channel = custom.get(log_type)
                    if channel is not None:
                        db.set_log_channel(ctx.guild.id, log_type, channel.id)
                        bound.append(log_type)
                        continue
                    if not create_channels:
                        skipped.append(log_type)
                        continue
                    name = CHANNEL_NAMES[log_type]
                    channel = discord.utils.get(category.channels, name=name)
                    if channel is None:
                        channel = await ctx.guild.create_text_channel(name, category=category)
                        created.append(log_type)
                    else:
                        reused.append(log_type)
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

            parts = []
            if bound:
                parts.append("bound your channels for **%s**"
                             % ", ".join(sorted(bound)))
            if created:
                parts.append("created channels for **%s**"
                             % ", ".join(sorted(created)))
            if reused:
                parts.append("kept the existing channels for **%s**"
                             % ", ".join(sorted(reused)))
            if skipped:
                parts.append("skipped **%s** (not set up)"
                             % ", ".join(sorted(skipped)))
            await ctx.followup.send(
                "✅ Logger configured. " + "; ".join(parts) + ".",
                ephemeral=True,
            )

    if WORKER_MODE:
        @logs.command(
            name="change_channel",
            description="Point one log category at a different channel.",
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
            from utils.permissions import check_slash_permission, _default_admin_only
            if not await check_slash_permission(
                    ctx, "logs_change_channel", _default_admin_only):
                return
            ok, why = _log_channel_usable(channel, ctx.guild.me)
            if not ok:
                await ctx.respond(
                    f"I can't use {channel.mention} for **{log_type}** "
                    f"logs: {why}.",
                    ephemeral=True,
                )
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

    if WORKER_MODE:
        @logs.command(
            name="settings",
            description="View logger configuration.",
        )
        async def log_settings(self, ctx):
            await ctx.defer(ephemeral=True)
            configured = db.get_all_log_channels(ctx.guild.id)
            embed = discord.Embed(title="📜 Logger Settings", color=discord.Color.blurple())
            for log_type in CATEGORIES:
                channel_id = configured.get(log_type)
                channel = ctx.guild.get_channel(channel_id) if channel_id else None
                value = channel.mention if channel else (
                    "⚠ Channel deleted" if channel_id else "Not configured"
                )
                embed.add_field(name=f"{log_type.capitalize()} logs", value=value, inline=True)
            disabled = [e for e in ALL_EVENTS if not db.is_enabled(ctx.guild.id, e)]
            embed.add_field(
                name="Disabled events",
                value=", ".join(f"`{e}`" for e in disabled) or "None \u2014 everything is on",
                inline=False,
            )
            await ctx.followup.send(embed=embed, ephemeral=True)
