"""Custom per-command permissions -- setup commands.

Admin-only commands to grant (or deny) a role or one user access to a
specific bot action, without turning on Discord's Administrator
permission for that role.

* /perm_allow -- grant a role or a user a command (allow or deny).
* /perm_remove -- remove a grant.
* /perm_list -- show what is set up in this server.

The rules live in the command_permissions table (shared SQLite db),
so the website reads the same table from the database file and can
enforce them even while the bot is offline (website side is a later
step). The check itself is in utils/permissions.py; this cog is only
the admin-facing setup. See utils/permissions.py for the precedence
(admin always allowed; user deny > user allow > role deny > role
allow; no rules at all falls back to the command's normal Discord
permission check; rules that exist but do not match deny).
"""

import discord
from discord.ext import commands

from config import GUILD_IDS, extra_help
from data.DB.Storage.storage import (
    delete_all_command_permissions,
    delete_command_permission,
    delete_command_permissions_for_command,
    delete_command_permissions_for_target,
    get_all_command_permissions,
    get_command_permissions,
    save_command_permission,
)
from utils.permissions import (
    BULK_COMMAND_GROUPS,
    GRANTABLE_CATEGORIES,
    GRANTABLE_COMMANDS,
    is_grantable,
)

# The command picker is an autocomplete, not a static choice list, so
# the grantable list can grow past Discord's 25-choice cap. The admin
# types a few letters and picks from the matches (up to 25 shown).
async def _command_autocomplete(ctx: discord.AutocompleteContext):
    """Grantable commands matching what the admin typed (name or
    description). Falls back to an empty list on any error so a
    hiccup never breaks the command itself."""
    try:
        query = (ctx.value or "").lower()
        choices = [
            discord.OptionChoice(name="%s - %s" % (name, desc), value=name)
            for name, desc in GRANTABLE_COMMANDS
            if query in name.lower() or query in desc.lower()
        ]
        return choices[:25]
    except Exception:
        return []


_GRANTABLE_DESC = dict(GRANTABLE_COMMANDS)

_RULE_CHOICES = ["allow", "deny"]


class BulkPermView(discord.ui.View):
    """Step 1 of the /perm_bulk builder: pick as many roles as you
    want (up to 25 at once), then Next shows every command at once."""

    def __init__(self, author_id: int, guild: discord.Guild):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild
        self.role_ids: list[int] = []

        role_select = discord.ui.RoleSelect(
            placeholder="Pick roles (up to 25 at once)",
            min_values=1,
            max_values=25,
        )
        role_select.callback = self._on_roles
        self.role_select = role_select
        self.add_item(role_select)

        next_button = discord.ui.Button(
            label="Next: pick commands", style=discord.ButtonStyle.primary
        )
        next_button.callback = self._on_next
        self.add_item(next_button)

        cancel_button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.grey
        )
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    async def _on_roles(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        self.role_ids = [r.id for r in self.role_select.values]
        await interaction.response.edit_message(
            content="Picked **%d** role%s. Hit **Next** to choose commands."
            % (len(self.role_ids), "s" if len(self.role_ids) != 1 else ""),
            view=self,
        )

    async def _on_next(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        if not self.role_ids:
            await interaction.response.send_message(
                "Pick at least one role first.", ephemeral=True
            )
            return
        cmd_view = BulkCommandView(self.author_id, self.guild, self.role_ids)
        await interaction.response.edit_message(
            content=(
                "Picked **%d** role%s. Tick commands in any (or all) of "
                "the four lists below -- every grantable command is "
                "shown at once. Then hit **Grant (allow)** or "
                "**Grant (deny)**."
                % (len(self.role_ids), "s" if len(self.role_ids) != 1 else "")
            ),
            view=cmd_view,
        )
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Bulk grant cancelled -- nothing was changed.",
            view=self,
        )
        self.stop()


class BulkCommandView(discord.ui.View):
    """Step 2 of the /perm_bulk builder: every grantable command is
    shown at once in four multi-select lists (Discord caps a select
    at 25 options). Tick commands in any or all of them; picks stay
    ticked when you move to another list. Grant defers first, so a
    big grant (many roles x many commands) never times out."""

    def __init__(self, author_id: int, guild: discord.Guild, role_ids):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild = guild
        self.role_ids = list(role_ids)
        self.commands: set[str] = set()
        self.selects = []
        for label, cmds in BULK_COMMAND_GROUPS:
            sel = discord.ui.Select(
                placeholder="%s (pick any)" % label,
                options=[
                    discord.SelectOption(
                        label=cmd,
                        value=cmd,
                        description=_GRANTABLE_DESC.get(cmd, "")[:100],
                    )
                    for cmd in cmds
                ],
                min_values=0,
                max_values=len(cmds),
            )
            sel.callback = self._make_on_commands(sel, cmds)
            self.selects.append(sel)
            self.add_item(sel)

        grant_allow = discord.ui.Button(
            label="Grant (allow)", style=discord.ButtonStyle.green
        )
        grant_allow.callback = self._on_grant_allow
        self.add_item(grant_allow)

        grant_deny = discord.ui.Button(
            label="Grant (deny)", style=discord.ButtonStyle.red
        )
        grant_deny.callback = self._on_grant_deny
        self.add_item(grant_deny)

        back_button = discord.ui.Button(
            label="Back to roles", style=discord.ButtonStyle.secondary
        )
        back_button.callback = self._on_back
        self.add_item(back_button)

        cancel_button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.grey
        )
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    def _make_on_commands(self, sel, group_cmds):
        async def _on_commands(interaction: discord.Interaction):
            if interaction.user.id != self.author_id:
                await interaction.response.send_message(
                    "Only the admin who opened this builder can use it.",
                    ephemeral=True,
                )
                return
            # Replace this group's picks with what is ticked now, and
            # re-mark the ticked options so they stay ticked when the
            # message is re-rendered (otherwise picks look lost).
            group = set(group_cmds)
            picked = {v for v in sel.values if v != "__none__"}
            self.commands = (self.commands - group) | picked
            for opt in sel.options:
                opt.default = opt.value in self.commands
            await interaction.response.edit_message(
                content=_bulk_cmd_status(self), view=self
            )

        return _on_commands

    async def _on_grant_allow(self, interaction: discord.Interaction):
        await self._do_grant(interaction, allowed=True)

    async def _on_grant_deny(self, interaction: discord.Interaction):
        await self._do_grant(interaction, allowed=False)

    async def _do_grant(self, interaction: discord.Interaction, allowed: bool):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        if not self.role_ids or not self.commands:
            await interaction.response.send_message(
                "Pick at least one role and at least one command first.",
                ephemeral=True,
            )
            return
        # Defer first: a big grant (many roles x many commands) does
        # a database write per grant, which can take longer than
        # Discord's 3-second interaction window.
        await interaction.response.defer(ephemeral=True)
        created = 0
        for role_id in self.role_ids:
            for cmd in sorted(self.commands):
                await save_command_permission(
                    str(self.guild.id), cmd, "role", str(role_id),
                    allowed, str(self.author_id),
                )
                created += 1
        role_mentions = []
        for role_id in self.role_ids:
            role = self.guild.get_role(role_id)
            role_mentions.append(role.mention if role else "`%s`" % role_id)
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(
            content=(
                "Gave **%d** grant%s (%s) to %s:\n%s"
                % (
                    created,
                    "s" if created != 1 else "",
                    "allow" if allowed else "DENY",
                    ", ".join(role_mentions),
                    ", ".join("`%s`" % c for c in sorted(self.commands)),
                )
            ),
            view=self,
        )
        self.stop()

    async def _on_back(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        view = BulkPermView(self.author_id, self.guild)
        view.role_ids = list(self.role_ids)
        await interaction.response.edit_message(
            content="Picked **%d** role%s. Hit **Next** to choose commands."
            % (len(self.role_ids), "s" if len(self.role_ids) != 1 else ""),
            view=view,
        )
        self.stop()

    async def _on_cancel(self, interaction: discord.Interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this builder can use it.",
                ephemeral=True,
            )
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Bulk grant cancelled -- nothing was changed.",
            view=self,
        )
        self.stop()


def _bulk_cmd_status(view):
    """Status line for the command-picking step."""
    return (
        "Picked **%d** role%s and **%d** command%s so far. "
        "Tick commands in any of the four lists -- your picks stay "
        "ticked."
        % (
            len(view.role_ids), "s" if len(view.role_ids) != 1 else "",
            len(view.commands), "s" if len(view.commands) != 1 else "",
        )
    )


def _is_admin(ctx):
    perms = ctx.author.guild_permissions if ctx.guild else None
    return bool(perms and perms.administrator)


def _target_label(guild, target_type, target_id):
    """Human label for a stored grant target (role/user name, else id)."""
    try:
        tid = int(target_id)
    except (TypeError, ValueError):
        return "%s %s" % (target_type, target_id)
    if target_type == "role":
        role = guild.get_role(tid) if guild else None
        return "role @%s" % role.name if role else "role %s" % tid
    member = guild.get_member(tid) if guild else None
    if member is not None:
        return "user %s" % member.display_name
    return "user %s" % tid


def _role_sort_key(guild, role_id):
    """Sort roles for /perm_overview: highest in the hierarchy first,
    then by name. Unknown roles sort last."""
    try:
        role = guild.get_role(int(role_id))
    except (TypeError, ValueError):
        role = None
    if role is None:
        return (1, "")
    return (0, -role.position, role.name.lower())


def _chunk_embeds(title, color, fields, footer=None):
    """Pack (name, value) fields into as many embeds as needed.
    Discord caps an embed at 25 fields and 6000 characters total,
    and a field value at 1024 characters. Fields longer than that
    are split; when an embed would overflow, a new one starts."""
    embeds = []
    cur = discord.Embed(title=title, color=color)
    cur_len = len(title)
    if footer:
        cur.set_footer(text=footer)
        cur_len += len(footer)
    for name, value in fields:
        # Split on LINE boundaries, never mid-line: a hard 1024-char
        # cut can split a `command` code span or a <@&id> mention in
        # half, and an unmatched backtick makes Discord render the
        # rest of the chunk as code, so the mentions show as raw ids.
        lines = value.split("\n")
        chunks: list[str] = []
        cur_chunk = ""
        for line in lines:
            # A single line longer than the cap has no line boundary
            # to split on; cut it by characters as a last resort.
            while len(line) > 1024:
                if cur_chunk:
                    chunks.append(cur_chunk)
                    cur_chunk = ""
                chunks.append(line[:1024])
                line = line[1024:]
            piece = line if not cur_chunk else "\n" + line
            if cur_chunk and len(cur_chunk) + len(piece) > 1024:
                chunks.append(cur_chunk)
                cur_chunk = line
            else:
                cur_chunk += piece
        if cur_chunk or not chunks:
            chunks.append(cur_chunk)
        for j, chunk in enumerate(chunks):
            fname = name if j == 0 else "%s (cont.)" % name
            if len(fname) > 256:
                fname = fname[:256]
            f_len = len(fname) + len(chunk)
            if len(cur.fields) >= 25 or cur_len + f_len > 5900:
                embeds.append(cur)
                cur = discord.Embed(title="%s (cont.)" % title, color=color)
                if footer:
                    cur.set_footer(text=footer)
                cur_len = len(title) + (len(footer) if footer else 0)
            cur.add_field(name=fname, value=chunk or "(none)", inline=False)
            cur_len += f_len
    if cur.fields:
        embeds.append(cur)
    return embeds


def _role_name(guild, target_id):
    """Plain role name for embed FIELD NAMES. Mentions do not render
    in field names (they show as raw <@&id>), so a field name must
    use the name as plain text."""
    try:
        role = guild.get_role(int(target_id)) if guild else None
    except (TypeError, ValueError):
        role = None
    if role is not None:
        return role.name
    return "%s (deleted role)" % target_id


def _role_display(guild, target_id):
    """Role as a mention (renders as a coloured @Name pill) when it
    exists; the id with a marker when the role is gone (deleted roles
    stay in the grants table, and a mention of a missing role renders
    as raw <@&id> text). Use only in embed field VALUES, never in
    field names."""
    try:
        role = guild.get_role(int(target_id)) if guild else None
    except (TypeError, ValueError):
        role = None
    if role is not None:
        return role.mention
    return "%s (deleted role)" % target_id


def _user_display(guild, target_id):
    """Member as a mention when they are in the server, else the id
    with a marker."""
    try:
        member = guild.get_member(int(target_id)) if guild else None
    except (TypeError, ValueError):
        member = None
    if member is not None:
        return member.mention
    return "%s (left server)" % target_id


class Permissions(commands.Cog):
    """Admin-only setup for the custom per-command permissions system."""

    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="perm_allow",
        description="Grant (or deny) a role or user a command.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Give a role a command (e.g. Trial Moderator can use timeout "
        "but not ban), or give ONE user a command for training without "
        "changing the whole role. Pick exactly one of role or user. "
        "A deny beats an allow. Server admins always keep access."
    )
    async def perm_allow(
        self,
        ctx,
        command: discord.Option(str, "Which command/action (start typing to pick)", autocomplete=_command_autocomplete),  # type: ignore
        role: discord.Option(discord.Role, "Role to grant it to", required=False, default=None),  # type: ignore
        user: discord.Option(discord.Member, "One user to grant it to (training)", required=False, default=None),  # type: ignore
        rule: discord.Option(str, "allow or deny", choices=_RULE_CHOICES, required=False, default="allow"),  # type: ignore
    ):
        if ctx.guild is None:
            await ctx.respond("Use this in a server.", ephemeral=True)
            return
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if not is_grantable(command):
            await ctx.respond(
                "`%s` is not a command custom permissions can be set for. "
                "Pick one from the autocomplete list." % command,
                ephemeral=True,
            )
            return
        if (role is None) == (user is None):
            await ctx.respond(
                "Pick exactly one: a role OR a user.",
                ephemeral=True,
            )
            return
        target_type = "role" if role is not None else "user"
        target_id = role.id if role is not None else user.id
        target_name = role.name if role is not None else user.display_name
        allowed = rule != "deny"
        await save_command_permission(
            str(ctx.guild.id), command, target_type, str(target_id),
            allowed, str(ctx.author),
        )
        verb = "can now use" if allowed else "is now DENIED from using"
        await ctx.respond(
            "%s%s %s `%s`.%s" % (
                "Role @" if target_type == "role" else "User ",
                target_name,
                verb,
                command,
                "\nServer admins always keep access." if allowed else "",
            ),
            ephemeral=True,
        )

    @discord.slash_command(
        name="perm_remove",
        description="Remove a custom permission grant.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Remove a role or user grant for one command, so the command "
        "falls back to its normal Discord permission check (or to the "
        "role's other rules, if any)."
    )
    async def perm_remove(
        self,
        ctx,
        command: discord.Option(str, "Which command/action (start typing to pick)", autocomplete=_command_autocomplete),  # type: ignore
        role: discord.Option(discord.Role, "Role to remove it from", required=False, default=None),  # type: ignore
        user: discord.Option(discord.Member, "User to remove it from", required=False, default=None),  # type: ignore
    ):
        if ctx.guild is None:
            await ctx.respond("Use this in a server.", ephemeral=True)
            return
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if not is_grantable(command):
            await ctx.respond(
                "`%s` is not a command custom permissions can be set for. "
                "Pick one from the autocomplete list." % command,
                ephemeral=True,
            )
            return
        if (role is None) == (user is None):
            await ctx.respond(
                "Pick exactly one: a role OR a user.",
                ephemeral=True,
            )
            return
        target_type = "role" if role is not None else "user"
        target_id = role.id if role is not None else user.id
        target_name = role.name if role is not None else user.display_name
        removed = await delete_command_permission(
            str(ctx.guild.id), command, target_type, str(target_id)
        )
        if removed:
            await ctx.respond(
                "Removed the `%s` grant for %s %s." % (
                    command,
                    "role @" if target_type == "role" else "user ",
                    target_name,
                ),
                ephemeral=True,
            )
        else:
            await ctx.respond(
                "There was no `%s` grant for %s %s to remove." % (
                    command,
                    "role @" if target_type == "role" else "user ",
                    target_name,
                ),
                ephemeral=True,
            )

    @discord.slash_command(
        name="perm_list",
        description="Show the custom permission grants in this server.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "List every custom permission grant in this server, or just the "
        "grants for one command. Commands with no grants use their "
        "normal Discord permission check."
    )
    async def perm_list(
        self,
        ctx,
        command: discord.Option(str, "Only show grants for this command (start typing to pick)", autocomplete=_command_autocomplete, required=False, default=None),  # type: ignore
    ):
        if ctx.guild is None:
            await ctx.respond("Use this in a server.", ephemeral=True)
            return
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can view custom permissions.",
                ephemeral=True,
            )
            return
        if command:
            grants = await get_command_permissions(str(ctx.guild.id), command)
        else:
            grants = await get_all_command_permissions(str(ctx.guild.id))
        if not grants:
            await ctx.respond(
                "No custom permission grants are set in this server."
                if not command
                else "No custom permission grants are set for `%s`." % command,
                ephemeral=True,
            )
            return
        lines = []
        for grant in grants:
            label = _target_label(
                ctx.guild, grant.get("target_type"), grant.get("target_id")
            )
            verdict = "allow" if grant.get("allowed") else "DENY"
            lines.append(
                "`%s` -- %s (%s)" % (grant.get("command"), label, verdict)
            )
        title = (
            "Custom permissions for `%s`" % command
            if command
            else "Custom permissions in this server"
        )
        embed = discord.Embed(title=title, color=discord.Color.blurple())
        # Keep the embed under Discord's field limits; split if needed.
        chunk = ""
        field_no = 1
        for line in lines:
            if len(chunk) + len(line) + 1 > 1000:
                embed.add_field(
                    name="Grants %d" % field_no, value=chunk, inline=False
                )
                field_no += 1
                chunk = ""
            chunk += line + "\n"
        if chunk:
            embed.add_field(
                name="Grants %d" % field_no, value=chunk, inline=False
            )
        embed.set_footer(
            text="Server admins always keep access. Commands with no "
            "grants use their normal Discord permission check."
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(
        name="perm_bulk",
        description="Grant many roles many commands at once (multi-select builder)",
        guild_ids=GUILD_IDS,
    )
    async def perm_bulk(
        self,
        ctx: discord.ApplicationContext,
    ):
        """Open the bulk builder: pick as many roles as you want, then
        tick as many commands as you want from the four lists (every
        grantable command is shown at once), then Grant."""
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        view = BulkPermView(ctx.author.id, ctx.guild)
        await ctx.respond(
            content=(
                "Pick roles (up to 25 at once), then hit **Next** to "
                "choose commands. Every grantable command is shown in "
                "four lists -- tick as many as you want, in any of them."
            ),
            view=view,
            ephemeral=True,
        )

    @discord.slash_command(
        name="perm_commands",
        description="Show every command and which roles (and users) have it",
        guild_ids=GUILD_IDS,
    )
    async def perm_commands(
        self,
        ctx: discord.ApplicationContext,
    ):
        """Command-centric overview: for every grantable command, the
        roles (and any per-user grants) linked to it, all at once,
        grouped by category. Commands with no custom grants fall back
        to their normal Discord permission check."""
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        grants = await get_all_command_permissions(str(ctx.guild.id))
        # Group by command: command -> (allowed role/user labels, denied labels).
        by_command: dict[str, dict[str, list[str]]] = {}
        for g in grants:
            cmd = g.get("command")
            tid = str(g.get("target_id"))
            if g.get("target_type") == "role":
                label = _role_display(ctx.guild, tid)
            else:
                label = _user_display(ctx.guild, tid) + " (user)"
            slot = by_command.setdefault(cmd, {"allow": [], "deny": []})
            slot["allow" if g.get("allowed") else "deny"].append(label)
        fields: list[tuple[str, str]] = []
        for category, cmds in GRANTABLE_CATEGORIES:
            lines = []
            for cmd in cmds:
                slot = by_command.get(cmd, {"allow": [], "deny": []})
                allows = slot["allow"]
                denies = slot["deny"]
                if not allows and not denies:
                    lines.append("`%s`: no custom grants" % cmd)
                else:
                    bits = []
                    if allows:
                        bits.append(", ".join(allows))
                    if denies:
                        bits.append("denied: %s" % ", ".join(denies))
                    lines.append("`%s`: %s" % (cmd, "; ".join(bits)))
            fields.append((category, "\n".join(lines)))
        embeds = _chunk_embeds(
            "All commands and who can run them",
            discord.Color.green(),
            fields,
            footer=(
                "Commands with no custom grants use their normal Discord "
                "permission check. Per-user grants are marked (user)."
            ),
        )
        print(
            "[PERM] /perm_commands: %d fields -> %d embeds, sizes=%s"
            % (len(fields), len(embeds), [len(e) for e in embeds]),
            flush=True,
        )
        # Discord caps the TOTAL characters across all embeds in one
        # message at 6000, not just each embed, so send one embed per
        # message: the first as the reply, the rest as followups.
        await ctx.respond(embed=embeds[0], ephemeral=True)
        for extra in embeds[1:]:
            await ctx.followup.send(embed=extra, ephemeral=True)

    @discord.slash_command(
        name="perm_overview",
        description="Show what each role can do, and any per-user grants",
        guild_ids=GUILD_IDS,
    )
    async def perm_overview(
        self,
        ctx: discord.ApplicationContext,
    ):
        """Embed: for every role with grants, the commands it can run
        (and any denies); plus a separate section for per-user grants
        -- the individual overrides that give one person a command
        their roles would not otherwise give them."""
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        grants = await get_all_command_permissions(str(ctx.guild.id))
        if not grants:
            await ctx.respond(
                "No custom permission grants are set in this server. "
                "Use /perm_allow or /perm_bulk to add some.",
                ephemeral=True,
            )
            return
        # Group by target.
        roles: dict[str, list] = {}
        users: dict[str, list] = {}
        for g in grants:
            if g.get("target_type") == "role":
                roles.setdefault(str(g.get("target_id")), []).append(g)
            else:
                users.setdefault(str(g.get("target_id")), []).append(g)
        fields: list[tuple[str, str]] = []
        # Roles first: one field per role. The field NAME must be the
        # plain role name, not a mention: Discord does not render
        # mentions in field names, they show as raw <@&id>.
        for role_id in sorted(roles, key=lambda r: _role_sort_key(ctx.guild, r)):
            label = _role_name(ctx.guild, role_id)
            allows = sorted(
                g.get("command") for g in roles[role_id] if g.get("allowed")
            )
            denies = sorted(
                g.get("command") for g in roles[role_id] if not g.get("allowed")
            )
            value = ""
            if allows:
                value += "Can run: %s" % ", ".join("`%s`" % c for c in allows)
            if denies:
                if value:
                    value += "\n"
                value += "Denied: %s" % ", ".join("`%s`" % c for c in denies)
            fields.append((label, value or "(no commands)"))
        # Per-user grants: the individual overrides.
        if users:
            lines = []
            for user_id in sorted(users):
                label = _user_display(ctx.guild, user_id)
                allows = sorted(
                    g.get("command") for g in users[user_id] if g.get("allowed")
                )
                denies = sorted(
                    g.get("command") for g in users[user_id] if not g.get("allowed")
                )
                bits = []
                if allows:
                    bits.append("can run %s" % ", ".join("`%s`" % c for c in allows))
                if denies:
                    bits.append("denied %s" % ", ".join("`%s`" % c for c in denies))
                lines.append("%s -- %s" % (label, "; ".join(bits)))
            fields.append(("Individual user grants", "\n".join(lines)))
        embeds = _chunk_embeds(
            "Custom permissions in this server",
            discord.Color.blurple(),
            fields,
            footer=(
                "Server admins always keep access. Commands with no "
                "grants use their normal Discord permission check. "
                "Per-user grants override what the person's roles allow."
            ),
        )
        print(
            "[PERM] /perm_overview: %d fields -> %d embeds, sizes=%s"
            % (len(fields), len(embeds), [len(e) for e in embeds]),
            flush=True,
        )
        # Discord caps the TOTAL characters across all embeds in one
        # message at 6000, not just each embed, so send one embed per
        # message: the first as the reply, the rest as followups.
        await ctx.respond(embed=embeds[0], ephemeral=True)
        for extra in embeds[1:]:
            await ctx.followup.send(embed=extra, ephemeral=True)

    @discord.slash_command(
        name="perm_reset",
        description="Remove custom permission grants (preview first, confirm to delete)",
        guild_ids=GUILD_IDS,
    )
    async def perm_reset(
        self,
        ctx: discord.ApplicationContext,
        role: discord.Option(discord.Role, "Remove every grant for this role", required=False, default=None),  # type: ignore
        user: discord.Option(discord.Member, "Remove every grant for this user", required=False, default=None),  # type: ignore
        command: discord.Option(str, "Remove every grant for this command (start typing to pick)", autocomplete=_command_autocomplete, required=False, default=None),  # type: ignore
        confirm: discord.Option(bool, "Set to True to actually delete (default: just preview)", required=False, default=False),  # type: ignore
    ):
        """Reset custom permissions: one role, one user, one command,
        or everything. Without confirm=True it only shows what would
        be removed, so a bad grant can be undone safely."""
        if not _is_admin(ctx):
            await ctx.respond(
                "Only a server admin can set up custom permissions.",
                ephemeral=True,
            )
            return
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        filters = [x for x in (role, user, command) if x is not None]
        if len(filters) > 1:
            await ctx.respond(
                "Pick only one filter (a role, a user, or a command) -- "
                "or none at all to reset everything.",
                ephemeral=True,
            )
            return
        if command is not None and not is_grantable(command):
            await ctx.respond(
                "`%s` is not a command custom permissions can be set for."
                % command,
                ephemeral=True,
            )
            return
        grants = await get_all_command_permissions(str(ctx.guild.id))
        if role is not None:
            scope = "role %s" % role.mention
            matching = [
                g for g in grants
                if g.get("target_type") == "role"
                and str(g.get("target_id")) == str(role.id)
            ]
        elif user is not None:
            scope = "user %s" % user.mention
            matching = [
                g for g in grants
                if g.get("target_type") == "user"
                and str(g.get("target_id")) == str(user.id)
            ]
        elif command is not None:
            scope = "command `%s`" % command
            matching = [g for g in grants if g.get("command") == command]
        else:
            scope = "everything in this server"
            matching = list(grants)
        if not matching:
            await ctx.respond(
                "Nothing to reset for %s -- no custom permission grants match."
                % scope,
                ephemeral=True,
            )
            return
        if not confirm:
            preview = []
            for g in matching[:15]:
                label = _target_label(
                    ctx.guild, g.get("target_type"), g.get("target_id")
                )
                verdict = "allow" if g.get("allowed") else "DENY"
                preview.append(
                    "`%s` -- %s (%s)" % (g.get("command"), label, verdict)
                )
            if len(matching) > 15:
                preview.append("...and %d more" % (len(matching) - 15))
            await ctx.respond(
                "This would remove **%d** grant%s for %s:\n%s\n\n"
                "Re-run with `confirm: True` to actually delete them."
                % (
                    len(matching),
                    "s" if len(matching) != 1 else "",
                    scope,
                    "\n".join(preview),
                ),
                ephemeral=True,
            )
            return
        if role is not None:
            removed = await delete_command_permissions_for_target(
                str(ctx.guild.id), "role", str(role.id)
            )
        elif user is not None:
            removed = await delete_command_permissions_for_target(
                str(ctx.guild.id), "user", str(user.id)
            )
        elif command is not None:
            removed = await delete_command_permissions_for_command(
                str(ctx.guild.id), command
            )
        else:
            removed = await delete_all_command_permissions(str(ctx.guild.id))
        await ctx.respond(
            "Removed **%d** grant%s for %s. Commands with no grants "
            "left use their normal Discord permission check."
            % (
                removed,
                "s" if removed != 1 else "",
                scope,
            ),
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(Permissions(bot))
