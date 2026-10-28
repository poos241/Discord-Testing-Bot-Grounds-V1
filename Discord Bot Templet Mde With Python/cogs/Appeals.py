"""Appeals + mod notes search (built 2026-10-27).

Appeals: a member who was banned or timed out can appeal, and staff
can review the appeal and lift the punishment (or deny it) from one
place. Two ways in, because banned users cannot use guild commands:

- In the server: /appeal submit (type + why it should be lifted).
  Works for timeouts, and for anyone still in the server.
- Banned (or otherwise out of the server): DM the bot the word
  `appeal`. The bot replies with a "Start appeal" button, which opens
  a modal (ban/timeout + why). The ban/timeout DMs sent by the mod
  panel now mention this, so people find it.

One pending appeal per user per server. Submitting a second one while
the first is still pending is refused and points at the open one.

Review flow (staff only): /appeal list shows pending appeals,
/appeal review <id> shows the appeal plus the original case it is
appealing (pulled from mod_data.json, same records the mod panel
writes), with Approve / Deny buttons.
- Approve a ban appeal: unbans the user (and clears any tempban
  entry) and records an "appeal_approved" case.
- Approve a timeout appeal: removes the timeout if the user is
  still in the server, and records an "appeal_approved" case.
- Deny: asks for a reason in a modal, records "appeal_denied",
  and DMs the appellant the outcome either way (best effort —
  closed DMs just mean no DM, the decision still stands).

Per-server config: /appeal config sets the channel new appeals are
posted to and the staff role. When no staff role is set, staff is
anyone with Manage Messages or Administrator (same fallback the
ticket system uses); changing config needs Manage Server or
Administrator.

Mod notes search: /modnotes search <keyword> [user] (staff only).
Searches mod_data.json for the server — mod notes, warn reasons,
and case reasons — case-insensitively, newest first, capped at 10
shown with a total count. This is the read side of the notes the
mod panel already writes; it changes nothing.

Storage: two new tables in models.py (appeal_guild_config,
appeals) + helpers in data/DB/Storage/storage.py. create_all()
creates the new tables on the next bot boot; no existing table
is altered and mod_data.json keeps working exactly as before.

No web blueprint: appeals are reviewed in Discord, where the mods
already work the mod panel. A web review page is a possible
follow-up, not part of this build.
"""

import time
from datetime import datetime, timezone

import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands

from config import GUILD_IDS, load_json
from data.DB.db import database
from data.DB.Storage.storage import (
    get_appeal_guild_config,
    save_appeal_guild_config,
    create_appeal,
    get_appeal,
    list_appeals,
    get_pending_appeal_for_user,
    update_appeal,
)
from cogs.admin_cog import _record_case, _tempban_data, _save_mod_data

EMBED_COLOR = 0x5865F2
MOD_DATA_FILE = "mod_data.json"
MAX_SEARCH_RESULTS = 10


async def ensure_db():
    """Connect the shared database if nothing else has yet (same
    check the Tickets/QOTD cogs use). Safe to call often."""
    try:
        if not database.is_connected:
            await database.connect()
    except Exception as e:
        print(f"[APPEALS] DB connect check failed: {e!r}")


def is_mod(member):
    """Manage Messages or Administrator, matching the ticket/mod checks."""
    if member is None:
        return False
    perms = member.guild_permissions
    return bool(perms.manage_messages or perms.administrator)


def is_admin(member):
    """Manage Server or Administrator, matching the mod panel check."""
    if member is None:
        return False
    perms = member.guild_permissions
    return bool(perms.manage_guild or perms.administrator)


def is_appeal_staff(member, cfg):
    """Configured staff role, or the Manage Messages / Administrator
    fallback when no staff role is set (same shape as ticket staff)."""
    if member is None:
        return False
    if member.guild_permissions.administrator:
        return True
    staff_role_id = (cfg or {}).get("staff_role_id")
    if staff_role_id:
        return any(str(r.id) == str(staff_role_id) for r in member.roles)
    return is_mod(member)


def _fmt_ts(ts):
    """mod_data.json stores epoch seconds; the new SQLite tables store
    datetimes. Accept both so one formatter serves both sources."""
    try:
        if isinstance(ts, datetime):
            return ts.strftime("%Y-%m-%d")
        return datetime.fromtimestamp(float(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except Exception:
        return "?"


def latest_case_for(guild_id, user_id, appeal_type):
    """The most recent mod_data.json case matching this appeal type:
    ban appeals match 'ban' / 'tempban (...)' cases, timeout appeals
    match 'timeout' cases. Returns the case dict or None."""
    data = load_json(MOD_DATA_FILE) or {}
    cases = (
        data.get(str(guild_id), {}).get(str(user_id), {}).get("cases", [])
    )
    for case in reversed(cases):
        action = str(case.get("action", ""))
        if appeal_type == "ban" and (action == "ban" or action.startswith("tempban")):
            return case
        if appeal_type == "timeout" and action == "timeout":
            return case
    return None


def appeal_embed(appeal, guild_name=None):
    """Embed describing one appeal row, including its original case."""
    status_colors = {
        "pending": EMBED_COLOR,
        "approved": 0x57F287,
        "denied": 0xED4245,
    }
    embed = discord.Embed(
        title=f"Appeal #{appeal['id']} — {appeal['appeal_type']}",
        color=status_colors.get(appeal["status"], EMBED_COLOR),
    )
    embed.add_field(name="Appellant", value=f"<@{appeal['user_id']}>", inline=True)
    embed.add_field(name="Status", value=appeal["status"], inline=True)
    if guild_name:
        embed.add_field(name="Server", value=guild_name, inline=True)
    embed.add_field(name="Their words", value=appeal["text"][:1000], inline=False)
    case = latest_case_for(appeal["guild_id"], appeal["user_id"], appeal["appeal_type"])
    if case:
        extra = case.get("extra") or {}
        dur = extra.get("duration")
        case_text = f"{case.get('action', '?')}: {case.get('reason', 'No reason given')}"
        if dur:
            case_text += f" ({dur})"
        case_text += f"\n— {case.get('mod_name', '?')} • {_fmt_ts(case.get('ts', 0))}"
        embed.add_field(name="Original case", value=case_text[:1000], inline=False)
    else:
        embed.add_field(
            name="Original case",
            value="_No matching ban/timeout case found in mod records._",
            inline=False,
        )
    if appeal.get("decided_by"):
        decision = f"Decided by <@{appeal['decided_by']}>"
        if appeal.get("decision_reason"):
            decision += f"\nReason: {appeal['decision_reason']}"
        embed.add_field(name="Decision", value=decision[:1000], inline=False)
    return embed


async def post_to_appeals_channel(guild, appeal):
    """Post a new appeal to the configured appeals channel, if any.
    Never raises: a missing channel must not break the submission."""
    cfg = await get_appeal_guild_config(str(guild.id))
    channel_id = (cfg or {}).get("appeals_channel_id")
    if not channel_id:
        return False
    try:
        channel = guild.get_channel(int(channel_id))
        if channel is None:
            return False
        await channel.send(
            f"New appeal — review it with `/appeal review {appeal['id']}`:",
            embed=appeal_embed(appeal, guild_name=guild.name),
        )
        return True
    except Exception as e:
        print(f"[APPEALS] Could not post appeal #{appeal['id']}: {e!r}")
        return False


async def dm_user(bot, user_id, text):
    """Best-effort DM. Returns True when delivered."""
    try:
        user = bot.get_user(int(user_id)) or await bot.fetch_user(int(user_id))
        await user.send(text)
        return True
    except Exception:
        return False


async def create_appeal_for(bot, guild, user_id, user_name, appeal_type, text):
    """Shared submit path for the slash command and the DM flow.
    Returns (appeal_dict, existing_pending_or_None)."""
    await ensure_db()
    existing = await get_pending_appeal_for_user(str(guild.id), str(user_id))
    if existing:
        return None, existing
    appeal = await create_appeal(
        str(guild.id), str(user_id), user_name, appeal_type, text
    )
    return appeal, None


class DenyModal(discord.ui.Modal):
    """Reason for denying an appeal, asked when staff hit Deny."""

    def __init__(self, cog, appeal):
        super().__init__(title=f"Deny appeal #{appeal['id']}"[:45])
        self.cog = cog
        self.appeal = appeal
        self.add_item(discord.ui.InputText(
            label="Reason for denying",
            style=discord.InputTextStyle.paragraph,
            placeholder="Why is this appeal denied?",
            max_length=500,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or "No reason given"
        await self.cog.finish_decision(interaction, self.appeal, "denied", reason)


class AppealReviewView(discord.ui.View):
    """Approve / Deny buttons on a /appeal review message (5 min)."""

    def __init__(self, cog, appeal):
        super().__init__(timeout=300)
        self.cog = cog
        self.appeal = appeal

    @discord.ui.button(label="Approve", emoji="✅", style=discord.ButtonStyle.success)
    async def approve_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await self.cog.finish_decision(interaction, self.appeal, "approved", "")

    @discord.ui.button(label="Deny", emoji="❌", style=discord.ButtonStyle.danger)
    async def deny_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(DenyModal(self.cog, self.appeal))


class AppealStartView(discord.ui.View):
    """'Start appeal' button sent to someone who DMs the bot 'appeal'."""

    def __init__(self, cog, guild):
        super().__init__(timeout=300)
        self.cog = cog
        self.guild = guild

    @discord.ui.button(label="Start appeal", emoji="📝", style=discord.ButtonStyle.primary)
    async def start_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(DmAppealModal(self.cog, self.guild))


class AppealGuildSelectView(discord.ui.View):
    """Guild picker for the DM flow when the bot is in several servers."""

    def __init__(self, cog, guilds):
        super().__init__(timeout=300)
        self.cog = cog
        select = discord.ui.Select(
            placeholder="Which server is this appeal for?",
            options=[
                discord.SelectOption(label=g.name[:100], value=str(g.id))
                for g in guilds[:25]
            ],
        )
        select.callback = self._picked
        self.add_item(select)

    async def _picked(self, interaction: discord.Interaction):
        guild = self.cog.bot.get_guild(int(interaction.data["values"][0]))
        if guild is None:
            await interaction.response.send_message(
                "❌ That server isn't available anymore.", ephemeral=True
            )
            return
        await interaction.response.send_message(
            f"Appealing in **{guild.name}** — click below to write it:",
            view=AppealStartView(self.cog, guild),
            ephemeral=True,
        )


class DmAppealModal(discord.ui.Modal):
    """The appeal itself, from the DM flow (banned users can't use
    guild slash commands, so this is their way in)."""

    def __init__(self, cog, guild):
        super().__init__(title=f"Appeal in {guild.name}"[:45])
        self.cog = cog
        self.guild = guild
        self.add_item(discord.ui.InputText(
            label="Ban or timeout?",
            placeholder="Type ban or timeout",
            max_length=20,
        ))
        self.add_item(discord.ui.InputText(
            label="Why should it be lifted?",
            style=discord.InputTextStyle.paragraph,
            placeholder="Say what happened and why you should be let back in…",
            max_length=1000,
        ))

    async def callback(self, interaction: discord.Interaction):
        appeal_type = (self.children[0].value or "").strip().lower()
        text = (self.children[1].value or "").strip()
        if appeal_type not in ("ban", "timeout"):
            await interaction.response.send_message(
                "❌ First field must be `ban` or `timeout`. Send `appeal` again to retry.",
                ephemeral=True,
            )
            return
        if not text:
            await interaction.response.send_message(
                "❌ Your appeal can't be empty. Send `appeal` again to retry.",
                ephemeral=True,
            )
            return
        appeal, existing = await create_appeal_for(
            self.cog.bot, self.guild, interaction.user.id,
            str(interaction.user), appeal_type, text,
        )
        if existing:
            await interaction.response.send_message(
                f"You already have a pending appeal in **{self.guild.name}** "
                f"(appeal #{existing['id']}). Staff will review it — please "
                "don't open another one.",
                ephemeral=True,
            )
            return
        posted = await post_to_appeals_channel(self.guild, appeal)
        note = (
            "\nStaff have been notified."
            if posted else
            "\n_Staff haven't set an appeals channel yet, but your appeal is "
            "recorded and staff can review it with `/appeal list`._"
        )
        await interaction.response.send_message(
            f"✅ Appeal #{appeal['id']} submitted in **{self.guild.name}**.{note}",
            ephemeral=True,
        )


class Appeals(commands.Cog):
    """Ban/timeout appeals + keyword search across mod notes/warns."""

    appeal = SlashCommandGroup("appeal", "Appeal a ban or timeout", guild_ids=GUILD_IDS)
    modnotes = SlashCommandGroup("modnotes", "Search mod notes and warns", guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot

    # ---------- DM flow: banned users DM the bot "appeal" ----------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is not None or message.author.bot:
            return
        text = (message.content or "").strip().lower()
        if text != "appeal" and not text.startswith("appeal "):
            return
        guilds = [g for g in self.bot.guilds]
        if not guilds:
            await message.channel.send(
                "I'm not in any servers right now, so there's nothing to appeal."
            )
            return
        if len(guilds) == 1:
            guild = guilds[0]
            await message.channel.send(
                f"To appeal in **{guild.name}**, click below and fill in the form:",
                view=AppealStartView(self, guild),
            )
        else:
            await message.channel.send(
                "Which server is this appeal for?",
                view=AppealGuildSelectView(self, guilds),
            )

    # ---------- /appeal commands ----------

    @appeal.command(name="submit", description="Appeal a ban or timeout.")
    async def appeal_submit(
        self,
        ctx,
        appeal_type: discord.Option(str, "What are you appealing?", choices=["ban", "timeout"]),
        details: discord.Option(str, "Why should it be lifted?", max_length=1000),
    ):
        if ctx.guild is None:
            await ctx.respond(
                "Appeals from DMs work differently: just DM me the word `appeal` "
                "and I'll walk you through it.",
                ephemeral=True,
            )
            return
        appeal, existing = await create_appeal_for(
            self.bot, ctx.guild, ctx.author.id, str(ctx.author),
            appeal_type, (details or "").strip() or "No details given",
        )
        if existing:
            await ctx.respond(
                f"You already have a pending appeal (appeal #{existing['id']}). "
                "Staff will review it — please don't open another one.",
                ephemeral=True,
            )
            return
        posted = await post_to_appeals_channel(ctx.guild, appeal)
        note = (
            "\nStaff have been notified."
            if posted else
            "\n_Staff haven't set an appeals channel yet, but your appeal is "
            "recorded and staff can review it with `/appeal list`._"
        )
        await ctx.respond(
            f"✅ Appeal #{appeal['id']} submitted.{note}",
            ephemeral=True,
        )

    @appeal.command(name="list", description="List appeals (staff only).")
    async def appeal_list(
        self,
        ctx,
        status: discord.Option(
            str, "Which appeals to show", required=False, default="pending",
            choices=["pending", "approved", "denied", "all"],
        ),
    ):
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        await ensure_db()
        cfg = await get_appeal_guild_config(str(ctx.guild.id))
        if not is_appeal_staff(ctx.author, cfg):
            await ctx.respond("You need to be staff to list appeals.", ephemeral=True)
            return
        rows = await list_appeals(str(ctx.guild.id), None if status == "all" else status)
        if not rows:
            await ctx.respond(f"No {status} appeals.", ephemeral=True)
            return
        lines = []
        for row in rows[:20]:
            lines.append(
                f"**#{row['id']}** — {row['appeal_type']} — <@{row['user_id']}> — "
                f"{row['status']} — {_fmt_ts(row['created_at']) if row.get('created_at') else '?'}"
            )
        if len(rows) > 20:
            lines.append(f"_…and {len(rows) - 20} more._")
        await ctx.respond(
            f"Appeals ({status}):\n" + "\n".join(lines) +
            "\n\nReview one with `/appeal review <id>`.",
            ephemeral=True,
        )

    @appeal.command(name="review", description="Review one appeal (staff only).")
    async def appeal_review(
        self,
        ctx,
        appeal_id: discord.Option(int, "Appeal number, e.g. 3"),
    ):
        if ctx.guild is None:
            await ctx.respond("Use this command in a server.", ephemeral=True)
            return
        await ensure_db()
        cfg = await get_appeal_guild_config(str(ctx.guild.id))
        if not is_appeal_staff(ctx.author, cfg):
            await ctx.respond("You need to be staff to review appeals.", ephemeral=True)
            return
        appeal = await get_appeal(int(appeal_id))
        if appeal is None or str(appeal["guild_id"]) != str(ctx.guild.id):
            await ctx.respond(f"❌ No appeal #{appeal_id} in this server.", ephemeral=True)
            return
        if appeal["status"] != "pending":
            await ctx.respond(
                f"Appeal #{appeal_id} is already {appeal['status']}.",
                embed=appeal_embed(appeal, guild_name=ctx.guild.name),
                ephemeral=True,
            )
            return
        await ctx.respond(
            embed=appeal_embed(appeal, guild_name=ctx.guild.name),
            view=AppealReviewView(self, appeal),
            ephemeral=True,
        )

    @appeal.command(name="config", description="Set the appeals channel / staff role (server admins).")
    async def appeal_config(
        self,
        ctx,
        channel: discord.Option(discord.TextChannel, "Channel new appeals get posted to", required=False, default=None),
        staff_role: discord.Option(discord.Role, "Role that counts as appeal staff", required=False, default=None),
    ):
        if ctx.guild is None or not is_admin(ctx.author):
            await ctx.respond(
                "You need Manage Server or Administrator to change appeal settings.",
                ephemeral=True,
            )
            return
        await ensure_db()
        payload = {}
        if channel is not None:
            payload["appeals_channel_id"] = str(channel.id)
        if staff_role is not None:
            payload["staff_role_id"] = str(staff_role.id)
        if not payload:
            cfg = await get_appeal_guild_config(str(ctx.guild.id))
            await ctx.respond(
                "Current appeal settings:\n"
                f"• Channel: <#{cfg.get('appeals_channel_id')}>"
                if cfg.get("appeals_channel_id") else
                "Current appeal settings:\n• Channel: _not set_",
                ephemeral=True,
            )
            return
        await save_appeal_guild_config(str(ctx.guild.id), payload)
        await ctx.respond("✅ Appeal settings saved.", ephemeral=True)

    async def finish_decision(self, interaction, appeal, status, reason):
        """Apply an Approve/Deny from the review view (or deny modal).
        Re-checks staff + pending state, lifts the punishment on
        approve, records a case, and DMs the appellant."""
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message(
                "Decisions have to be made in the server.", ephemeral=True
            )
            return
        await ensure_db()
        cfg = await get_appeal_guild_config(str(guild.id))
        if not is_appeal_staff(interaction.user, cfg):
            await interaction.response.send_message(
                "You need to be staff to decide appeals.", ephemeral=True
            )
            return
        fresh = await get_appeal(int(appeal["id"]))
        if fresh is None or fresh["status"] != "pending":
            await interaction.response.send_message(
                "That appeal was already decided.", ephemeral=True
            )
            return
        result_note = ""
        if status == "approved":
            if appeal["appeal_type"] == "ban":
                try:
                    await guild.unban(
                        discord.Object(id=int(appeal["user_id"])),
                        reason=f"Appeal #{appeal['id']} approved by {interaction.user}",
                    )
                    result_note = "User unbanned."
                except discord.NotFound:
                    result_note = "User wasn't actually banned — nothing to unban."
                except discord.Forbidden:
                    await interaction.response.send_message(
                        "❌ I can't unban them — check my permissions. The appeal is still pending.",
                        ephemeral=True,
                    )
                    return
                except Exception as e:
                    await interaction.response.send_message(
                        f"❌ Unban failed: `{e}` — the appeal is still pending.",
                        ephemeral=True,
                    )
                    return
                try:
                    tb_data, tb = _tempban_data(guild.id)
                    tb.pop(str(appeal["user_id"]), None)
                    _save_mod_data(tb_data)
                except Exception:
                    pass
            else:  # timeout
                member = guild.get_member(int(appeal["user_id"]))
                if member is None:
                    result_note = "User isn't in the server, so there's no timeout to lift."
                else:
                    try:
                        await member.remove_timeout(
                            reason=f"Appeal #{appeal['id']} approved by {interaction.user}"
                        )
                        result_note = "Timeout removed."
                    except discord.Forbidden:
                        await interaction.response.send_message(
                            "❌ I can't remove that timeout — is my role above theirs? The appeal is still pending.",
                            ephemeral=True,
                        )
                        return
                    except Exception as e:
                        await interaction.response.send_message(
                            f"❌ Removing the timeout failed: `{e}` — the appeal is still pending.",
                            ephemeral=True,
                        )
                        return
            _record_case(
                guild.id, int(appeal["user_id"]), "appeal_approved",
                f"Appeal #{appeal['id']} approved: {result_note}",
                interaction.user,
            )
        else:  # denied
            _record_case(
                guild.id, int(appeal["user_id"]), "appeal_denied",
                f"Appeal #{appeal['id']} denied: {reason}",
                interaction.user,
            )
        await update_appeal(int(appeal["id"]), {
            "status": status,
            "decided_by": str(interaction.user.id),
            "decision_reason": reason,
            "decided_at": datetime.now(timezone.utc),
        })
        decided = await get_appeal(int(appeal["id"]))
        dm_text = (
            f"Your appeal in **{guild.name}** was **{status}**."
            + (f"\nReason: {reason}" if reason else "")
        )
        dm_ok = await dm_user(self.bot, appeal["user_id"], dm_text)
        try:
            await interaction.response.edit_message(
                content=(
                    f"Appeal #{appeal['id']} **{status}**. {result_note} "
                    f"DM to appellant: {'sent' if dm_ok else 'could not be delivered (DMs closed?)'}."
                ),
                embed=appeal_embed(decided, guild_name=guild.name),
                view=None,
            )
        except Exception:
            # Deny came via modal, so there is no review message to edit.
            await interaction.response.send_message(
                f"Appeal #{appeal['id']} **{status}**. {result_note} "
                f"DM to appellant: {'sent' if dm_ok else 'could not be delivered (DMs closed?)'}.",
                ephemeral=True,
            )

    # ---------- /modnotes search ----------

    @modnotes.command(name="search", description="Keyword search across mod notes, warns, and cases (staff only).")
    async def modnotes_search(
        self,
        ctx,
        keyword: discord.Option(str, "Word or phrase to search for"),
        user: discord.Option(discord.Member, "Only search this member's records", required=False, default=None),
    ):
        if ctx.guild is None or not is_mod(ctx.author):
            await ctx.respond(
                "You need Manage Messages or Administrator to search mod notes.",
                ephemeral=True,
            )
            return
        needle = (keyword or "").strip().lower()
        if not needle:
            await ctx.respond("❌ Give me a keyword to search for.", ephemeral=True)
            return
        data = load_json(MOD_DATA_FILE) or {}
        grec = data.get(str(ctx.guild.id), {})
        matches = []
        user_ids = [str(user.id)] if user is not None else list(grec.keys())
        for uid in user_ids:
            if uid == "tempbans":
                continue
            urec = grec.get(uid)
            if not isinstance(urec, dict):
                continue
            for note in urec.get("notes", []):
                text = note.get("text", "")
                if needle in text.lower():
                    matches.append((note.get("ts", 0), uid, "note", text,
                                    note.get("mod_name", "?")))
            for warn in urec.get("warns", []):
                text = warn.get("reason", "")
                if needle in text.lower():
                    matches.append((warn.get("ts", 0), uid, "warn", text,
                                    warn.get("mod_name", "?")))
            for case in urec.get("cases", []):
                text = case.get("reason", "")
                haystack = f"{case.get('action', '')} {text}".lower()
                if needle in haystack:
                    matches.append((case.get("ts", 0), uid,
                                    f"case ({case.get('action', '?')})", text,
                                    case.get("mod_name", "?")))
        matches.sort(key=lambda m: m[0], reverse=True)
        if not matches:
            scope = f" for {user.mention}" if user is not None else ""
            await ctx.respond(
                f"No mod notes, warns, or cases matching `{keyword}`{scope}.",
                ephemeral=True,
            )
            return
        lines = []
        for ts, uid, kind, text, mod_name in matches[:MAX_SEARCH_RESULTS]:
            snippet = (text or "").replace("\n", " ")
            if len(snippet) > 120:
                snippet = snippet[:117] + "…"
            lines.append(
                f"**{kind}** — <@{uid}> — {mod_name} • {_fmt_ts(ts)}\n> {snippet}"
            )
        extra = ""
        if len(matches) > MAX_SEARCH_RESULTS:
            extra = f"\n_Showing {MAX_SEARCH_RESULTS} of {len(matches)} matches — narrow the keyword or add a user to see more._"
        await ctx.respond(
            f"Matches for `{keyword}` ({len(matches)}):\n\n" + "\n".join(lines) + extra,
            ephemeral=True,
        )


def setup(bot):
    bot.add_cog(Appeals(bot))
