"""Support ticket system, built NEW from the ground up (2026-10-27).

This replaces nothing and salvages nothing from any earlier ticket
attempt: there is no old ticket cog in this repo, and the legacy
ticket_config / active_tickets / ticket_records tables in models.py
are left completely untouched. This system uses its own tables
(ticket_guild_config, support_tickets) with one row per ticket, so
tickets can be listed, claimed, and logged without digging through
JSON blobs.

How it works:
- A mod posts a ticket panel with /ticket panel (or sets a panel
  channel with /ticket config). Members click "Open a ticket",
  type a short topic in a modal, and get a private channel named
  ticket-0001, ticket-0002, ... (per-server numbering).
- Only the opener and staff can see a ticket channel. Staff is the
  configured staff role, or — when no staff role is set — anyone
  with Manage Messages or Administrator.
- One open ticket per member per server. Trying to open a second
  one points at the existing channel instead of making a duplicate.
- Closing locks the channel for the opener (read-only), renames it
  to closed-0001, logs a summary to the staff/log channel when one
  is configured, and leaves Reopen + Delete buttons for staff.
  Channels are never auto-deleted, so nothing is lost by accident.
- Staff can claim a ticket (so two mods don't work the same one),
  and add/remove members from a ticket channel.
- The panel button and the in-channel buttons use persistent views
  (timeout=None + stable custom_ids, re-registered in __init__ like
  the Eat It or Yeet It views), so they keep working across restarts.
- All commands are guild-scoped slash commands under /ticket.

Per-server config (ticket_guild_config): staff role, ticket
category, log channel, panel channel/message, next ticket number.
"""

import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands

from config import GUILD_IDS
from data.DB.db import database
from data.DB.Storage.storage import (
    get_ticket_guild_config,
    save_ticket_guild_config,
    create_support_ticket,
    get_ticket_by_channel,
    get_open_ticket_for_user,
    list_open_tickets,
    update_support_ticket,
)

EMBED_COLOR = 0x5865F2


def is_mod(ctx):
    """Manage Messages or Administrator, matching this bot's mod checks."""
    if ctx.guild is None:
        return False
    perms = ctx.author.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


async def ensure_db():
    """Connect the shared database if nothing else has yet (same
    check the QOTD cog uses before its loop). Safe to call often."""
    try:
        if not database.is_connected:
            await database.connect()
    except Exception as e:
        print(f"[TICKETS] DB connect check failed: {e!r}")


def is_staff(member, cfg):
    """True when this member counts as ticket staff for the guild."""
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    staff_role_id = (cfg or {}).get("staff_role_id")
    if staff_role_id:
        return any(str(r.id) == str(staff_role_id) for r in member.roles)
    perms = member.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


def staff_overwrites(guild, cfg):
    """Permission overwrites granting staff read/send in a ticket
    channel: the configured staff role, or every role with Manage
    Messages / Administrator when no staff role is set."""
    full = discord.PermissionOverwrite(
        read_messages=True, send_messages=True,
        attach_files=True, embed_links=True, read_message_history=True,
    )
    overwrites = {}
    staff_role_id = (cfg or {}).get("staff_role_id")
    if staff_role_id:
        role = guild.get_role(int(staff_role_id))
        if role is not None:
            overwrites[role] = full
            return overwrites
        # Configured role is gone: fall through to the perm fallback.
    for role in guild.roles:
        if role.permissions.manage_messages or role.permissions.administrator:
            overwrites[role] = full
    return overwrites


def ticket_channel_name(number, closed=False):
    prefix = "closed" if closed else "ticket"
    return f"{prefix}-{int(number):04d}"


async def log_to_staff_channel(guild, cfg, embed):
    """Send an embed to the configured log channel, if any. Never
    raises: a missing log channel must not break the ticket action."""
    log_id = (cfg or {}).get("log_channel_id")
    if not log_id:
        return
    try:
        channel = guild.get_channel(int(log_id))
        if channel is not None:
            await channel.send(embed=embed)
    except Exception as e:
        print(f"[TICKETS] Could not send to log channel {log_id}: {e!r}")


async def create_ticket_channel(guild, opener, cfg, topic):
    """Create the private ticket channel + DB row. Returns
    (channel, ticket_dict). Caller handles the user-facing reply."""
    number = int((cfg or {}).get("next_number") or 1)
    category = None
    category_id = (cfg or {}).get("category_id")
    if category_id:
        category = guild.get_channel(int(category_id))
        if category is not None and not isinstance(category, discord.CategoryChannel):
            category = None
    overwrites = {
        guild.default_role: discord.PermissionOverwrite(read_messages=False),
        opener: discord.PermissionOverwrite(
            read_messages=True, send_messages=True,
            attach_files=True, embed_links=True, read_message_history=True,
        ),
    }
    overwrites.update(staff_overwrites(guild, cfg))
    if guild.me is not None:
        overwrites[guild.me] = discord.PermissionOverwrite(
            read_messages=True, send_messages=True, manage_channels=True,
        )
    channel = await guild.create_text_channel(
        ticket_channel_name(number),
        category=category,
        overwrites=overwrites,
        topic=f"Ticket #{number:04d} opened by {opener} - {topic}"[:1024],
    )
    ticket = await create_support_ticket(
        str(guild.id), number, str(opener.id), str(channel.id), topic
    )
    await save_ticket_guild_config(str(guild.id), {"next_number": number + 1})
    return channel, ticket


async def post_ticket_intro(channel, opener, number, topic):
    """First message inside a new ticket channel, with the staff
    buttons (Close, Claim) attached."""
    embed = discord.Embed(
        title=f"Ticket #{number:04d}",
        description=f"Opened by {opener.mention}\n\n**Topic:** {topic}",
        color=EMBED_COLOR,
    )
    embed.set_footer(text="Staff: use the buttons below to close or claim this ticket.")
    await channel.send(
        content=opener.mention,
        embed=embed,
        view=TicketChannelView(),
    )


class TopicModal(discord.ui.Modal):
    """Topic prompt shown after clicking 'Open a ticket' on the panel."""

    def __init__(self):
        super().__init__(title="Open a ticket")
        self.add_item(discord.ui.InputText(
            label="What do you need help with?",
            style=discord.InputTextStyle.long,
            placeholder="Briefly describe your issue or request...",
            required=False,
            max_length=500,
        ))

    async def callback(self, interaction: discord.Interaction):
        await ensure_db()
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Tickets only work in a server.", ephemeral=True)
            return
        topic = (self.children[0].value or "").strip() or "No topic given"
        existing = await get_open_ticket_for_user(str(guild.id), str(interaction.user.id))
        if existing:
            channel = guild.get_channel(int(existing["channel_id"]))
            where = channel.mention if channel is not None else "your open ticket"
            await interaction.response.send_message(
                f"You already have an open ticket: {where}. Please use that one "
                "instead of opening a second ticket.",
                ephemeral=True)
            return
        cfg = await get_ticket_guild_config(str(guild.id))
        try:
            channel, ticket = await create_ticket_channel(
                guild, interaction.user, cfg, topic)
        except discord.Forbidden:
            await interaction.response.send_message(
                "I don't have permission to create ticket channels here. A mod "
                "needs to check my channel permissions.",
                ephemeral=True)
            return
        except Exception as e:
            print(f"[TICKETS] Ticket create failed: {e!r}")
            await interaction.response.send_message(
                "Something went wrong creating your ticket. Please try again "
                "or ask a mod for help.",
                ephemeral=True)
            return
        await post_ticket_intro(channel, interaction.user, ticket["number"], topic)
        await log_to_staff_channel(guild, cfg, discord.Embed(
            title=f"Ticket #{ticket['number']:04d} opened",
            description=f"{interaction.user.mention} opened a ticket: {topic}",
            color=EMBED_COLOR,
        ))
        await interaction.response.send_message(
            f"Your ticket is ready: {channel.mention}", ephemeral=True)


class TicketPanelView(discord.ui.View):
    """Persistent panel view: one button that opens the topic modal."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Open a ticket", style=discord.ButtonStyle.primary,
        emoji="\U0001f4e9", custom_id="tickets:panel_open")
    async def open_button(self, button, interaction: discord.Interaction):
        await interaction.response.send_modal(TopicModal())


class TicketChannelView(discord.ui.View):
    """Persistent buttons pinned to a ticket channel's intro message:
    Close (opener or staff) and Claim (staff)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Close ticket", style=discord.ButtonStyle.danger,
        emoji="\U0001f512", custom_id="tickets:close")
    async def close_button(self, button, interaction: discord.Interaction):
        await close_ticket_flow(interaction, reason="Closed from the ticket button.")

    @discord.ui.button(
        label="Claim / Unclaim", style=discord.ButtonStyle.secondary,
        emoji="\U0001f64b", custom_id="tickets:claim")
    async def claim_button(self, button, interaction: discord.Interaction):
        await claim_ticket_flow(interaction)


class TicketClosedView(discord.ui.View):
    """Persistent buttons posted when a ticket closes: Reopen
    (opener or staff) and Delete channel (staff)."""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="Reopen ticket", style=discord.ButtonStyle.success,
        emoji="\U0001f513", custom_id="tickets:reopen")
    async def reopen_button(self, button, interaction: discord.Interaction):
        await reopen_ticket_flow(interaction)

    @discord.ui.button(
        label="Delete channel", style=discord.ButtonStyle.danger,
        emoji="\U0001f5d1\ufe0f", custom_id="tickets:delete")
    async def delete_button(self, button, interaction: discord.Interaction):
        await delete_ticket_flow(interaction)


async def _ticket_for_interaction(interaction):
    """(ticket_dict, cfg) for the channel an interaction happened in,
    or (None, cfg) when the channel is not a ticket channel."""
    await ensure_db()
    guild = interaction.guild
    if guild is None:
        return None, {}
    cfg = await get_ticket_guild_config(str(guild.id))
    ticket = await get_ticket_by_channel(str(guild.id), str(interaction.channel.id))
    return ticket, cfg


async def close_ticket_flow(interaction, reason=None):
    """Shared by the Close button and /ticket close."""
    ticket, cfg = await _ticket_for_interaction(interaction)
    if ticket is None:
        await interaction.response.send_message(
            "This channel is not a ticket channel.", ephemeral=True)
        return
    if ticket.get("status") != "open":
        await interaction.response.send_message(
            "This ticket is already closed.", ephemeral=True)
        return
    member = interaction.user
    if str(member.id) != str(ticket["user_id"]) and not is_staff(member, cfg):
        await interaction.response.send_message(
            "Only the ticket opener or staff can close this ticket.",
            ephemeral=True)
        return
    channel = interaction.channel
    await update_support_ticket(ticket["id"], {
        "status": "closed",
        "closed_by": str(member.id),
        "close_reason": reason or "",
    })
    try:
        await channel.edit(
            name=ticket_channel_name(ticket["number"], closed=True),
            overwrites={
                **channel.overwrites,
                interaction.guild.get_member(int(ticket["user_id"])): discord.PermissionOverwrite(
                    read_messages=True, send_messages=False,
                    read_message_history=True),
            } if interaction.guild.get_member(int(ticket["user_id"])) else channel.overwrites,
        )
    except Exception as e:
        print(f"[TICKETS] Ticket close channel edit failed: {e!r}")
    embed = discord.Embed(
        title=f"Ticket #{ticket['number']:04d} closed",
        description=f"Closed by {member.mention}"
                    + (f"\n\n**Reason:** {reason}" if reason else ""),
        color=EMBED_COLOR,
    )
    await interaction.response.send_message(embed=embed)
    await channel.send(
        "This ticket is closed. Staff can reopen it or delete the channel.",
        view=TicketClosedView(),
    )
    await log_to_staff_channel(interaction.guild, cfg, discord.Embed(
        title=f"Ticket #{ticket['number']:04d} closed",
        description=f"Closed by {member.mention}"
                    + (f"\nReason: {reason}" if reason else ""),
        color=EMBED_COLOR,
    ))


async def claim_ticket_flow(interaction):
    """Staff claim toggle, shared by the Claim button and /ticket claim."""
    ticket, cfg = await _ticket_for_interaction(interaction)
    if ticket is None:
        await interaction.response.send_message(
            "This channel is not a ticket channel.", ephemeral=True)
        return
    if ticket.get("status") != "open":
        await interaction.response.send_message(
            "Only open tickets can be claimed.", ephemeral=True)
        return
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(
            "Only staff can claim tickets.", ephemeral=True)
        return
    if str(ticket.get("claimed_by") or "") == str(interaction.user.id):
        await update_support_ticket(ticket["id"], {"claimed_by": ""})
        await interaction.response.send_message(
            f"{interaction.user.mention} released the claim on this ticket.",
            ephemeral=False)
    else:
        await update_support_ticket(
            ticket["id"], {"claimed_by": str(interaction.user.id)})
        await interaction.response.send_message(
            f"{interaction.user.mention} claimed this ticket.",
            ephemeral=False)


async def reopen_ticket_flow(interaction):
    """Shared by the Reopen button and /ticket reopen."""
    ticket, cfg = await _ticket_for_interaction(interaction)
    if ticket is None:
        await interaction.response.send_message(
            "This channel is not a ticket channel.", ephemeral=True)
        return
    if ticket.get("status") != "closed":
        await interaction.response.send_message(
            "This ticket is not closed.", ephemeral=True)
        return
    member = interaction.user
    if str(member.id) != str(ticket["user_id"]) and not is_staff(member, cfg):
        await interaction.response.send_message(
            "Only the ticket opener or staff can reopen this ticket.",
            ephemeral=True)
        return
    channel = interaction.channel
    await update_support_ticket(ticket["id"], {
        "status": "open", "closed_by": "", "close_reason": "",
    })
    opener = interaction.guild.get_member(int(ticket["user_id"]))
    try:
        overwrites = dict(channel.overwrites)
        if opener is not None:
            overwrites[opener] = discord.PermissionOverwrite(
                read_messages=True, send_messages=True,
                attach_files=True, embed_links=True, read_message_history=True)
        await channel.edit(
            name=ticket_channel_name(ticket["number"]),
            overwrites=overwrites,
        )
    except Exception as e:
        print(f"[TICKETS] Ticket reopen channel edit failed: {e!r}")
    await interaction.response.send_message(
        embed=discord.Embed(
            title=f"Ticket #{ticket['number']:04d} reopened",
            description=f"Reopened by {member.mention}",
            color=EMBED_COLOR,
        ),
        view=TicketChannelView(),
    )


async def delete_ticket_flow(interaction):
    """Staff-only channel delete, shared by the Delete button and
    /ticket delete. Only for closed tickets, so an open ticket can
    never be deleted by a stray click."""
    ticket, cfg = await _ticket_for_interaction(interaction)
    if ticket is None:
        await interaction.response.send_message(
            "This channel is not a ticket channel.", ephemeral=True)
        return
    if not is_staff(interaction.user, cfg):
        await interaction.response.send_message(
            "Only staff can delete a ticket channel.", ephemeral=True)
        return
    if ticket.get("status") != "closed":
        await interaction.response.send_message(
            "Close the ticket first, then delete its channel.",
            ephemeral=True)
        return
    await interaction.response.send_message(
        "Deleting this ticket channel...", ephemeral=True)
    try:
        await interaction.channel.delete(reason=f"Ticket #{ticket['number']:04d} deleted by staff")
    except Exception as e:
        print(f"[TICKETS] Ticket channel delete failed: {e!r}")


class Tickets(commands.Cog):
    """Support tickets: panel, open/close, staff channel, per-server config."""

    ticket = SlashCommandGroup("ticket", "Support tickets", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        # Persistent views are registered in on_ready, NOT here: building
        # a View needs a running event loop, which does not exist yet when
        # this cog is loaded at startup (bot.py loads extensions before
        # run). Registering here crashed startup with "no running event loop".
        self._views_registered = False

    @commands.Cog.listener()
    async def on_ready(self):
        # Persistent views, so panel + ticket buttons survive restarts.
        # Guarded: on_ready also fires on reconnects.
        if self._views_registered:
            return
        self.bot.add_view(TicketPanelView())
        self.bot.add_view(TicketChannelView())
        self.bot.add_view(TicketClosedView())
        self._views_registered = True

    # ---------- mod setup commands ----------

    @ticket.command(name="panel", description="Post the ticket panel in this channel (mod only).")
    async def ticket_panel(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        await ensure_db()
        embed = discord.Embed(
            title="Need help? Open a ticket",
            description=(
                "Click the button below to open a private support ticket.\n"
                "Only you and staff will be able to see it.\n\n"
                "Please describe your issue briefly when asked, and a staff "
                "member will pick it up."
            ),
            color=EMBED_COLOR,
        )
        msg = await ctx.channel.send(embed=embed, view=TicketPanelView())
        await save_ticket_guild_config(str(ctx.guild.id), {
            "panel_channel_id": str(ctx.channel.id),
            "panel_message_id": str(msg.id),
        })
        await ctx.respond(
            "Ticket panel posted here. Members can now click it to open a ticket.",
            ephemeral=True)

    @ticket.command(name="config", description="Set the ticket settings for this server (mod only).")
    async def ticket_config_cmd(
        self,
        ctx,
        staff_role: discord.Option(discord.Role, "Role that counts as ticket staff", required=False, default=None),
        category: discord.Option(discord.CategoryChannel, "Category new ticket channels go under", required=False, default=None),
        log_channel: discord.Option(discord.TextChannel, "Channel ticket opens/closes get logged to", required=False, default=None),
        panel_channel: discord.Option(discord.TextChannel, "Channel the ticket panel lives in", required=False, default=None),
    ):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        await ensure_db()
        payload = {}
        if staff_role is not None:
            payload["staff_role_id"] = str(staff_role.id)
        if category is not None:
            payload["category_id"] = str(category.id)
        if log_channel is not None:
            payload["log_channel_id"] = str(log_channel.id)
        if panel_channel is not None:
            payload["panel_channel_id"] = str(panel_channel.id)
        if not payload:
            await ctx.respond(
                "Nothing to set — pass at least one option. See /ticket show "
                "for the current settings.",
                ephemeral=True)
            return
        await save_ticket_guild_config(str(ctx.guild.id), payload)
        await ctx.respond(
            "Ticket settings saved: " + ", ".join(
                f"{k} = {v}" for k, v in payload.items()),
            ephemeral=True)

    @ticket.command(name="show", description="Show the ticket settings for this server (mod only).")
    async def ticket_show(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        await ensure_db()
        cfg = await get_ticket_guild_config(str(ctx.guild.id))

        def _chan(cid):
            if not cid:
                return "not set"
            ch = ctx.guild.get_channel(int(cid))
            return ch.mention if ch is not None else f"(deleted channel {cid})"

        def _role(rid):
            if not rid:
                return "not set (staff = Manage Messages / Admins)"
            role = ctx.guild.get_role(int(rid))
            return role.mention if role is not None else f"(deleted role {rid})"

        embed = discord.Embed(title="Ticket settings", color=EMBED_COLOR)
        embed.add_field(name="Staff role", value=_role(cfg.get("staff_role_id")), inline=False)
        embed.add_field(name="Category", value=_chan(cfg.get("category_id")), inline=False)
        embed.add_field(name="Log channel", value=_chan(cfg.get("log_channel_id")), inline=False)
        embed.add_field(name="Panel channel", value=_chan(cfg.get("panel_channel_id")), inline=False)
        embed.add_field(name="Next ticket number", value=f"#{int(cfg.get('next_number') or 1):04d}", inline=False)
        await ctx.respond(embed=embed, ephemeral=True)

    # ---------- member commands ----------

    @ticket.command(name="open", description="Open a support ticket.")
    async def ticket_open(
        self,
        ctx,
        topic: discord.Option(str, "What do you need help with?", required=False, default=None),
    ):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await ensure_db()
        topic = (topic or "").strip() or "No topic given"
        existing = await get_open_ticket_for_user(str(ctx.guild.id), str(ctx.author.id))
        if existing:
            channel = ctx.guild.get_channel(int(existing["channel_id"]))
            where = channel.mention if channel is not None else "your open ticket"
            await ctx.respond(
                f"You already have an open ticket: {where}.",
                ephemeral=True)
            return
        cfg = await get_ticket_guild_config(str(ctx.guild.id))
        try:
            channel, ticket = await create_ticket_channel(
                ctx.guild, ctx.author, cfg, topic)
        except discord.Forbidden:
            await ctx.respond(
                "I don't have permission to create ticket channels here. "
                "A mod needs to check my channel permissions.",
                ephemeral=True)
            return
        except Exception as e:
            print(f"[TICKETS] Ticket create failed: {e!r}")
            await ctx.respond(
                "Something went wrong creating your ticket. Please try again "
                "or ask a mod for help.",
                ephemeral=True)
            return
        await post_ticket_intro(channel, ctx.author, ticket["number"], topic)
        await log_to_staff_channel(ctx.guild, cfg, discord.Embed(
            title=f"Ticket #{ticket['number']:04d} opened",
            description=f"{ctx.author.mention} opened a ticket: {topic}",
            color=EMBED_COLOR,
        ))
        await ctx.respond(f"Your ticket is ready: {channel.mention}", ephemeral=True)

    # ---------- in-ticket commands ----------

    @ticket.command(name="close", description="Close this ticket (opener or staff).")
    async def ticket_close(
        self,
        ctx,
        reason: discord.Option(str, "Why is this ticket being closed?", required=False, default=None),
    ):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await close_ticket_flow(ctx.interaction, reason=(reason or "").strip() or None)

    @ticket.command(name="reopen", description="Reopen this closed ticket (opener or staff).")
    async def ticket_reopen(self, ctx):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await reopen_ticket_flow(ctx.interaction)

    @ticket.command(name="claim", description="Claim (or release) this ticket (staff).")
    async def ticket_claim(self, ctx):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await claim_ticket_flow(ctx.interaction)

    @ticket.command(name="delete", description="Delete this closed ticket's channel (staff).")
    async def ticket_delete(self, ctx):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await delete_ticket_flow(ctx.interaction)

    @ticket.command(name="add", description="Add a member to this ticket channel (staff).")
    async def ticket_add(
        self,
        ctx,
        member: discord.Option(discord.Member, "Member to add to this ticket"),
    ):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await ensure_db()
        cfg = await get_ticket_guild_config(str(ctx.guild.id))
        ticket = await get_ticket_by_channel(str(ctx.guild.id), str(ctx.channel.id))
        if ticket is None:
            await ctx.respond("This channel is not a ticket channel.", ephemeral=True)
            return
        if not is_staff(ctx.author, cfg):
            await ctx.respond("Only staff can add members to a ticket.", ephemeral=True)
            return
        await ctx.channel.set_permissions(member, read_messages=True, send_messages=True,
                                          attach_files=True, embed_links=True,
                                          read_message_history=True)
        await ctx.respond(f"{member.mention} was added to this ticket.", ephemeral=True)

    @ticket.command(name="remove", description="Remove a member from this ticket channel (staff).")
    async def ticket_remove(
        self,
        ctx,
        member: discord.Option(discord.Member, "Member to remove from this ticket"),
    ):
        if ctx.guild is None:
            await ctx.respond("Ticket commands only work in a server.", ephemeral=True)
            return
        await ensure_db()
        cfg = await get_ticket_guild_config(str(ctx.guild.id))
        ticket = await get_ticket_by_channel(str(ctx.guild.id), str(ctx.channel.id))
        if ticket is None:
            await ctx.respond("This channel is not a ticket channel.", ephemeral=True)
            return
        if not is_staff(ctx.author, cfg):
            await ctx.respond("Only staff can remove members from a ticket.", ephemeral=True)
            return
        if str(member.id) == str(ticket["user_id"]):
            await ctx.respond("You can't remove the ticket opener — close the ticket instead.", ephemeral=True)
            return
        await ctx.channel.set_permissions(member, overwrite=None)
        await ctx.respond(f"{member.mention} was removed from this ticket.", ephemeral=True)

    @ticket.command(name="list", description="List this server's open tickets (mod only).")
    async def ticket_list(self, ctx):
        if ctx.guild is None or not is_mod(ctx):
            await ctx.respond("You need Manage Messages to use this command.", ephemeral=True)
            return
        await ensure_db()
        rows = await list_open_tickets(str(ctx.guild.id))
        if not rows:
            await ctx.respond("No open tickets right now.", ephemeral=True)
            return
        lines = []
        for row in rows:
            channel = ctx.guild.get_channel(int(row["channel_id"]))
            where = channel.mention if channel is not None else "(channel gone)"
            opener = ctx.guild.get_member(int(row["user_id"]))
            who = opener.mention if opener is not None else f"user {row['user_id']}"
            claimed = ""
            if row.get("claimed_by"):
                claimer = ctx.guild.get_member(int(row["claimed_by"]))
                claimed = f" — claimed by {claimer.mention if claimer else row['claimed_by']}"
            lines.append(f"**#{int(row['number']):04d}** {where} — {who} — {row.get('topic', '')}{claimed}")
        await ctx.respond(embed=discord.Embed(
            title="Open tickets", description="\n".join(lines), color=EMBED_COLOR,
        ), ephemeral=True)


def setup(bot):
    bot.add_cog(Tickets(bot))
