"""GitHub ban-log commands (manual log, v2).

/testbanlog posts one clearly-marked TEST draft item to prove the bot
can reach GitHub Projects at all. /banlog posts a real case: a member
(or a user ID for someone who already left), the action, the reason,
optional evidence links and an optional screenshot attachment, plus a
short summary of the bot's own case history for that user. Nothing posts
blind: both /banlog and the /userinfo panel button show an ephemeral
preview first, and only post when staff tap Post. /banlog_update changes
the Status/tags on an already-logged item or appends a dated note to its
body; /banlog_delete removes an item (type DELETE to confirm). Every
posted item is tracked in the ghlog_items table, so updates, deletes,
and duplicate warnings can find it again.

Target board defaults to the test board; switch it with
GITHUB_PROJECT_OWNER / GITHUB_PROJECT_NUMBER when the real board is
wired up. Rows record which board they live on, so an update never
fires at the wrong board after a switch.
"""

import datetime
import os
import re

import discord
from discord.ext import commands

from config import GUILD_IDS, admin_required, extra_help, load_json
from data.DB.Storage.storage import (
    delete_ghlog_item,
    list_ghlog_items,
    save_ghlog_item,
    update_ghlog_item,
)
from utils.github_projects import (
    PROJECT_NUMBER,
    PROJECT_OWNER,
    create_draft_issue,
    create_logged_case,
    delete_project_item,
    get_project_fields,
    get_project_id,
    resolve_draft_issue_id,
    set_single_select,
    update_draft_issue,
)

BOARD_URL = "https://github.com/users/%s/projects/%s" % (PROJECT_OWNER, PROJECT_NUMBER)

STATUS_CHOICES = [
    "Preds",
    "Intolerance e.g. transphobia, racism etc",
    "Trolls/Bullies",
    "Advertisers/Scammers",
    "Misc",
]

TAG_CHOICES = [
    "more info",
    "Blacklist approved",
]

# The panel modal takes Status/tags as free text (modals have no
# dropdowns), so typed values are matched forgivingly before posting.
# Anything still unmatched posts with a warning instead of failing.
STATUS_ALIASES = {
    "preds": "Preds",
    "intolerance": "Intolerance e.g. transphobia, racism etc",
    "trolls": "Trolls/Bullies",
    "bullies": "Trolls/Bullies",
    "advertisers": "Advertisers/Scammers",
    "scammers": "Advertisers/Scammers",
    "misc": "Misc",
}

TAG_ALIASES = {
    "more info": "more info",
    "blacklist": "Blacklist approved",
    "blacklist approved": "Blacklist approved",
}


def _utc_now():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _short_date(value):
    if value is None:
        return "?"
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    return str(value)[:10]


def normalize_option(value, choices, aliases):
    """Match a typed Status/tags value to a real board option, or None."""
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    if text in choices:
        return text
    hit = aliases.get(text.lower())
    if hit:
        return hit
    for choice in choices:
        if choice.lower() == text.lower():
            return choice
    return text


def format_case_history(guild_id, user_id):
    """Read-only summary of the bot's own mod record for this user.

    Uses plain .get lookups (never _mod_record's setdefault) so merely
    logging someone never creates or mutates a mod record.
    """
    try:
        data = load_json("mod_data.json") or {}
    except Exception:
        return "Prior record: unavailable (could not read mod data)."
    urec = data.get(str(guild_id), {}).get(str(user_id), {})
    cases = urec.get("cases", []) or []
    warns = urec.get("warns", []) or []
    lines = ["Prior record: %d case(s), %d warn(s)" % (len(cases), len(warns))]
    for case in reversed(cases[-5:]):
        try:
            date = datetime.datetime.fromtimestamp(
                float(case.get("ts", 0)), tz=datetime.timezone.utc
            ).strftime("%Y-%m-%d")
        except Exception:
            date = "?"
        lines.append(
            "- %s -- %s -- by %s -- %s"
            % (
                case.get("action", "?"),
                case.get("reason", ""),
                case.get("mod_name", "?"),
                date,
            )
        )
    return "\n".join(lines)


def build_case_body(action, server, logger, reason, evidence_links, guild_id, user_id):
    """Shared body builder for /banlog and the panel modal."""
    evidence_block = (
        "\n".join("- " + link for link in evidence_links)
        if evidence_links
        else "None provided"
    )
    if guild_id and user_id:
        history = format_case_history(guild_id, user_id)
    else:
        history = "Prior record: none on file."
    return (
        "Action: %s\n"
        "Server: %s\n"
        "Logged by: %s\n"
        "Date (UTC): %s\n"
        "Reason: %s\n"
        "Evidence:\n%s\n\n"
        "Case history (from bot records):\n%s"
        % (
            action,
            server,
            logger,
            _utc_now(),
            reason,
            evidence_block,
            history,
        )
    )


def build_preview_embed(title, body, status, tags, prior_items):
    """Ephemeral preview shown before anything posts (never the body raw:
    embeds cap at 4096 chars, so long histories are truncated here)."""
    desc = body if len(body) <= 4000 else body[:4000] + "\n... (full text posts to the board)"
    embed = discord.Embed(
        title="Preview -- about to post to GitHub",
        description=desc,
        color=discord.Color.orange(),
    )
    embed.add_field(name="Title", value=title, inline=False)
    embed.add_field(name="Status", value=status or "Not set", inline=True)
    embed.add_field(name="Tags", value=tags or "Not set", inline=True)
    if prior_items:
        lines = [
            "- %s -- %s" % (row.get("action", "?"), _short_date(row.get("created_at")))
            for row in prior_items[:3]
        ]
        embed.add_field(
            name="Already logged for this user", value="\n".join(lines), inline=False
        )
    return embed


class GHLogConfirmView(discord.ui.View):
    """Preview confirm step shared by /banlog and the panel modal.

    Non-persistent on purpose: it only has to live until staff tap Post
    or Cancel (or the 5-minute timeout disables it). The done flag stops
    a double-tap from posting twice.
    """

    def __init__(self, payload):
        super().__init__(timeout=300)
        self.payload = payload
        self.done = False
        self.message = None

    @discord.ui.button(label="Post to GitHub", style=discord.ButtonStyle.danger)
    async def confirm_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        p = self.payload
        if p.get("test_mode"):
            await interaction.response.edit_message(
                content="TEST -- nothing was posted.\n\nWould have posted:\n**%s**\n%s"
                % (p["title"], p["body"][:1500]),
                embed=None,
                view=None,
            )
            return
        await interaction.response.defer()
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            await interaction.edit_original_response(
                content="GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                embed=None,
                view=None,
            )
            return
        try:
            item_id, warnings = await create_logged_case(
                token, p["title"], p["body"], status=p.get("status"), tags=p.get("tags")
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content="GitHub post failed: %s" % exc, embed=None, view=None
            )
            return
        try:
            await save_ghlog_item(
                {
                    "guild_id": str(p["guild_id"]),
                    "user_id": str(p["user_id"]),
                    "display_name": p["display_name"],
                    "action": p["action"],
                    "item_id": item_id,
                    "draft_id": "",
                    "title": p["title"],
                    "body": p["body"],
                    "status": p.get("status") or "",
                    "tags": p.get("tags") or "",
                    "project_owner": PROJECT_OWNER,
                    "project_number": PROJECT_NUMBER,
                    "logged_by": p["logger_name"],
                }
            )
        except Exception:
            # The board post already succeeded; tracking is best-effort
            # and must never turn a success into a failure message.
            pass
        reply = "Case posted to the GitHub project: %s" % BOARD_URL
        if warnings:
            reply += "\nNotes: " + " ".join(warnings)
        await interaction.edit_original_response(content=reply, embed=None, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        await interaction.response.edit_message(
            content="Cancelled -- nothing was posted.", embed=None, view=None
        )

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class GHLogModal(discord.ui.Modal):
    """Log the panel's user to GitHub, prefilled from the last panel ban/kick."""

    def __init__(self, panel):
        target = panel.target
        name = target.display_name if isinstance(target, discord.Member) else target.name
        super().__init__(title="Log %s to GitHub" % name[:30])
        self.panel = panel
        self.guild = panel.guild
        self.target_id = panel.target_id
        self.target_name = name
        self.add_item(
            discord.ui.InputText(
                label="Action",
                style=discord.InputTextStyle.short,
                placeholder="Ban or Kick",
                value=panel.last_gh_action or "",
                max_length=10,
            )
        )
        self.add_item(
            discord.ui.InputText(
                label="Reason",
                style=discord.InputTextStyle.paragraph,
                placeholder="Why are they being logged?",
                value=panel.last_gh_reason or "",
                max_length=1000,
            )
        )
        self.add_item(
            discord.ui.InputText(
                label="Evidence links",
                style=discord.InputTextStyle.paragraph,
                placeholder="Links separated by spaces, or leave blank",
                required=False,
                max_length=1000,
            )
        )
        self.add_item(
            discord.ui.InputText(
                label="Status",
                style=discord.InputTextStyle.short,
                placeholder="Preds, Trolls, Advertisers, Misc, Intolerance",
                required=False,
                max_length=60,
            )
        )
        self.add_item(
            discord.ui.InputText(
                label="Tags",
                style=discord.InputTextStyle.short,
                placeholder="more info, or Blacklist approved",
                required=False,
                max_length=40,
            )
        )

    async def callback(self, interaction: discord.Interaction):
        action = (self.children[0].value or "").strip().lower()
        if action == "ban":
            action = "Ban"
        elif action == "kick":
            action = "Kick"
        else:
            await interaction.response.send_message(
                "Action must be Ban or Kick.", ephemeral=True
            )
            return
        reason = (self.children[1].value or "").strip()
        if not reason:
            await interaction.response.send_message(
                "Reason is required.", ephemeral=True
            )
            return
        links = (self.children[2].value or "").split()
        status = normalize_option(self.children[3].value, STATUS_CHOICES, STATUS_ALIASES)
        tags = normalize_option(self.children[4].value, TAG_CHOICES, TAG_ALIASES)
        title = "%s (%s)" % (self.target_name, self.target_id)
        body = build_case_body(
            action,
            self.guild.name,
            interaction.user.display_name,
            reason,
            links,
            self.guild.id,
            self.target_id,
        )
        try:
            prior = await list_ghlog_items(self.guild.id, self.target_id)
        except Exception:
            prior = []
        payload = {
            "title": title,
            "body": body,
            "action": action,
            "guild_id": self.guild.id,
            "user_id": self.target_id,
            "display_name": self.target_name,
            "status": status,
            "tags": tags,
            "logger_name": interaction.user.display_name,
            "test_mode": self.panel.test_mode,
        }
        view = GHLogConfirmView(payload)
        await interaction.response.send_message(
            embed=build_preview_embed(title, body, status, tags, prior),
            view=view,
            ephemeral=True,
        )
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass


class GHLog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @discord.slash_command(
        name="testbanlog",
        description="TEST: post a test entry to the GitHub ban-log project.",
        guild_ids=GUILD_IDS,
    )
    @admin_required()
    @extra_help(
        "Posts a clearly-marked TEST draft item to the test GitHub project. "
        "Proves the bot can reach GitHub Projects before any real case is logged."
    )
    async def testbanlog(self, ctx):
        await ctx.defer(ephemeral=True)
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            return await ctx.followup.send(
                "GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                ephemeral=True,
            )
        try:
            project_id = await get_project_id(token)
            body = (
                "TEST ENTRY - please delete.\n\n"
                "This is a connectivity probe from the bot's manual ban-log "
                "command. No real case is attached.\n\n"
                "Posted by: %s\n"
                "Server: %s\n"
                "Time (UTC): %s"
                % (
                    ctx.user.display_name,
                    ctx.guild.name if ctx.guild else "DM",
                    _utc_now(),
                )
            )
            await create_draft_issue(token, project_id, "TEST - GitHub ban log probe", body)
        except Exception as exc:
            return await ctx.followup.send(
                "GitHub post failed: %s" % exc,
                ephemeral=True,
            )
        await ctx.followup.send(
            "Test entry posted to the GitHub project (%s project %s). "
            "Check the board, then delete the TEST item."
            % (PROJECT_OWNER, PROJECT_NUMBER),
            ephemeral=True,
        )

    @discord.slash_command(
        name="banlog",
        description="Log a ban or kick to the GitHub ban-log project.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Posts a case to the GitHub ban-log project: title is the user plus "
        "their ID, body carries action, server, logger, date, reason, "
        "evidence links and screenshots, and a short case-history summary, "
        "and Status/tags are set when picked. Nothing posts until you confirm "
        "the preview. Pick a member if they are still in the server, otherwise "
        "paste an ID, mention, or username. Manage Server or Administrator only."
    )
    async def banlog(
        self,
        ctx,
        action: discord.Option(str, "What happened", choices=["Ban", "Kick"]),
        reason: discord.Option(str, "Why are they being logged?"),
        member: discord.Option(
            discord.Member,
            "Member to log (pick if they are still in the server)",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "User ID, mention, or username (use when they already left)",
            required=False,
            default=None,
        ),
        status: discord.Option(
            str, "Board status", required=False, default=None, choices=STATUS_CHOICES
        ),
        tags: discord.Option(
            str, "Board tag", required=False, default=None, choices=TAG_CHOICES
        ),
        evidence: discord.Option(
            str, "Evidence links, separated by spaces", required=False, default=None
        ),
        screenshot: discord.Option(
            discord.Attachment,
            "Screenshot evidence (its link is added to the case)",
            required=False,
            default=None,
        ),
    ):
        perms = ctx.user.guild_permissions if ctx.guild else None
        if perms is None or not (perms.administrator or perms.manage_guild):
            return await ctx.respond(
                "You need Manage Server or Administrator to log cases.",
                ephemeral=True,
            )
        target_id, display = await self._resolve_target(ctx, member, user_id)
        if display is None:
            return await ctx.respond(
                "Pick a member, or give a user ID, mention, or username I can find.",
                ephemeral=True,
            )
        await ctx.defer(ephemeral=True)
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            return await ctx.followup.send(
                "GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                ephemeral=True,
            )
        links = (evidence or "").split()
        if screenshot is not None:
            links = [screenshot.url] + links
        title = "%s (%s)" % (display, target_id) if target_id else "%s (ID unknown)" % display
        body = build_case_body(
            action,
            ctx.guild.name if ctx.guild else "DM",
            ctx.user.display_name,
            reason,
            links,
            ctx.guild.id if ctx.guild else None,
            target_id,
        )
        try:
            prior = await list_ghlog_items(ctx.guild.id, target_id) if ctx.guild else []
        except Exception:
            prior = []
        payload = {
            "title": title,
            "body": body,
            "action": action,
            "guild_id": ctx.guild.id if ctx.guild else None,
            "user_id": target_id,
            "display_name": display,
            "status": status,
            "tags": tags,
            "logger_name": ctx.user.display_name,
            "test_mode": False,
        }
        view = GHLogConfirmView(payload)
        msg = await ctx.followup.send(
            embed=build_preview_embed(title, body, status, tags, prior),
            view=view,
            ephemeral=True,
        )
        try:
            view.message = msg
        except Exception:
            pass

    @discord.slash_command(
        name="banlog_update",
        description="Update a logged case on the GitHub board.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Finds the most recent board item for a user and changes its Status "
        "and/or tags, and/or appends a dated note to its body. Give at least "
        "one of status, tags, or note. Only touches items logged while the "
        "bot pointed at the current board. Manage Server or Administrator only."
    )
    async def banlog_update(
        self,
        ctx,
        member: discord.Option(
            discord.Member,
            "Member to update (pick if they are still in the server)",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "User ID, mention, or username (use when they already left)",
            required=False,
            default=None,
        ),
        status: discord.Option(
            str, "New board status", required=False, default=None, choices=STATUS_CHOICES
        ),
        tags: discord.Option(
            str, "New board tag", required=False, default=None, choices=TAG_CHOICES
        ),
        note: discord.Option(
            str, "Note to append to the board item", required=False, default=None
        ),
    ):
        perms = ctx.user.guild_permissions if ctx.guild else None
        if perms is None or not (perms.administrator or perms.manage_guild):
            return await ctx.respond(
                "You need Manage Server or Administrator to update cases.",
                ephemeral=True,
            )
        target_id, display = await self._resolve_target(ctx, member, user_id)
        if display is None:
            return await ctx.respond(
                "Pick a member, or give a user ID, mention, or username I can find.",
                ephemeral=True,
            )
        if not status and not tags and not note:
            return await ctx.respond(
                "Give at least one of status, tags, or note to update.",
                ephemeral=True,
            )
        await ctx.defer(ephemeral=True)
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            return await ctx.followup.send(
                "GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                ephemeral=True,
            )
        try:
            rows = await list_ghlog_items(ctx.guild.id, target_id)
        except Exception:
            rows = []
        if not rows:
            return await ctx.followup.send(
                "No board item on file for %s -- log them with /banlog first."
                % display,
                ephemeral=True,
            )
        row = rows[0]
        if row.get("project_owner") != PROJECT_OWNER or row.get("project_number") != PROJECT_NUMBER:
            return await ctx.followup.send(
                "That item lives on the %s board (project %s), but the bot is "
                "now pointed at %s project %s. Switch the target back to "
                "update it."
                % (
                    row.get("project_owner"),
                    row.get("project_number"),
                    PROJECT_OWNER,
                    PROJECT_NUMBER,
                ),
                ephemeral=True,
            )
        try:
            project_id, fields = await get_project_fields(token)
            warnings = []
            updates = {}
            for field_name, option_name, column in (
                ("Status", status, "status"),
                ("tags", tags, "tags"),
            ):
                if not option_name:
                    continue
                field = fields.get(field_name)
                option_id = field["options"].get(option_name) if field else None
                if not option_id:
                    warnings.append(
                        "Board %s has no option %r; left unchanged."
                        % (field_name, option_name)
                    )
                    continue
                await set_single_select(
                    token, project_id, row["item_id"], field["id"], option_id
                )
                updates[column] = option_name
            if note:
                draft_id = row.get("draft_id") or await resolve_draft_issue_id(
                    token, row["item_id"]
                )
                new_body = "%s\n\n### Update -- %s by %s\n%s" % (
                    row.get("body") or "",
                    _utc_now(),
                    ctx.user.display_name,
                    note,
                )
                await update_draft_issue(token, draft_id, row["title"], new_body)
                updates["body"] = new_body
                updates["draft_id"] = draft_id
            if updates:
                await update_ghlog_item(row["id"], updates)
        except Exception as exc:
            return await ctx.followup.send(
                "Update failed: %s (any fields applied before the failure stay applied)."
                % exc,
                ephemeral=True,
            )
        changed = []
        if status:
            changed.append("Status -> %s" % status)
        if tags:
            changed.append("tags -> %s" % tags)
        if note:
            changed.append("note appended")
        reply = "Updated %s's board item (%s): %s" % (display, BOARD_URL, ", ".join(changed))
        if warnings:
            reply += "\nNotes: " + " ".join(warnings)
        await ctx.followup.send(reply, ephemeral=True)

    @discord.slash_command(
        name="banlog_delete",
        description="Delete a logged case from the GitHub board.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Deletes the most recent board item for a user (and its tracking "
        "row). Type DELETE exactly to confirm -- this cannot be undone. "
        "Manage Server or Administrator only."
    )
    async def banlog_delete(
        self,
        ctx,
        member: discord.Option(
            discord.Member,
            "Member to delete (pick if they are still in the server)",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "User ID, mention, or username (use when they already left)",
            required=False,
            default=None,
        ),
        confirm: discord.Option(
            str,
            "Type DELETE to confirm",
            # Discord rejects a command when a required option follows an
            # optional one, so confirm is optional in the form but still
            # enforced in code: anything other than DELETE refuses.
            required=False,
            default=None,
        ),
    ):
        perms = ctx.user.guild_permissions if ctx.guild else None
        if perms is None or not (perms.administrator or perms.manage_guild):
            return await ctx.respond(
                "You need Manage Server or Administrator to delete cases.",
                ephemeral=True,
            )
        if confirm != "DELETE":
            return await ctx.respond(
                "Type DELETE exactly to confirm -- nothing was deleted.",
                ephemeral=True,
            )
        target_id, display = await self._resolve_target(ctx, member, user_id)
        if display is None:
            return await ctx.respond(
                "Pick a member, or give a user ID, mention, or username I can find.",
                ephemeral=True,
            )
        await ctx.defer(ephemeral=True)
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            return await ctx.followup.send(
                "GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                ephemeral=True,
            )
        try:
            rows = await list_ghlog_items(ctx.guild.id, target_id)
        except Exception:
            rows = []
        if not rows:
            return await ctx.followup.send(
                "No board item on file for %s -- nothing to delete." % display,
                ephemeral=True,
            )
        row = rows[0]
        if row.get("project_owner") != PROJECT_OWNER or row.get("project_number") != PROJECT_NUMBER:
            return await ctx.followup.send(
                "That item lives on the %s board (project %s), but the bot is "
                "now pointed at %s project %s. Switch the target back to "
                "delete it."
                % (
                    row.get("project_owner"),
                    row.get("project_number"),
                    PROJECT_OWNER,
                    PROJECT_NUMBER,
                ),
                ephemeral=True,
            )
        try:
            project_id = await get_project_id(token)
            await delete_project_item(token, project_id, row["item_id"])
            await delete_ghlog_item(row["id"])
        except Exception as exc:
            return await ctx.followup.send(
                "Delete failed: %s" % exc,
                ephemeral=True,
            )
        await ctx.followup.send(
            "Deleted %s's board item." % display,
            ephemeral=True,
        )

    async def _resolve_target(self, ctx, member, user_id):
        """Return (user_id_str_or_None, display_name_or_None)."""
        if member is not None:
            return str(member.id), member.display_name
        if not user_id:
            return None, None
        raw = user_id.strip()
        mention = re.fullmatch(r"<@!?(\d+)>", raw)
        digits = mention.group(1) if mention else (raw if raw.isdigit() else None)
        if digits:
            try:
                user = await self.bot.fetch_user(int(digits))
                name = getattr(user, "display_name", None) or user.name
            except Exception:
                name = "Unknown user"
            return digits, name
        found = ctx.guild.get_member_named(raw) if ctx.guild else None
        if found is not None:
            return str(found.id), found.display_name
        return None, raw


def setup(bot):
    bot.add_cog(GHLog(bot))
