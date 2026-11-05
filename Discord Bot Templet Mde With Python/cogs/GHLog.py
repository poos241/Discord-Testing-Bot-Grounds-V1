"""GitHub ban-log commands (manual log, v2 + approval flow).

/testbanlog posts one clearly-marked TEST draft item to prove the bot
can reach GitHub Projects at all. /banlog posts a real case: a member
(or a user ID for someone who already left), the action, the reason,
optional evidence links, up to 10 screenshot attachments, and a ticket
number, plus a short summary of the bot's own case history for that
user. Nothing posts blind: both /banlog and the /userinfo panel button
show an ephemeral preview first, and only post when staff tap Post.

Approval flow: a new log does NOT go straight to its category. It
posts with Status "Needs approval", the Approval field set to
"Needs approval", and the tags field set to "pending approval", and
gets a case/log number (the tracking row id) in its title and body.
The bot OWNS the tags field for the approval state: the logger does
not pick a tag at log time. A second staff member then runs
/log_approve with that case number; the bot moves the item to the
category the logger picked (no override -- approve always uses the
logger's category), flips Approval to "Log approved", and flips the
tag to "approved". The approver must be someone other than the
logger. A tag is a single-select field, so it holds only ONE value at
a time: the approval state lives in "tags", and a separate "Decision"
field holds a human decision marker such as "Blacklist approved" or
"more info" (set it with /banlog_update). /banlog_update can still
change tags or append a note on a pending case, but it will not move
a pending case out of the holding column (use /log_approve for that).
/banlog_delete removes an item (type DELETE to confirm). Every posted
item is tracked in the ghlog_items table, so updates, deletes,
approvals, and duplicate warnings can find it again.

Evidence photos: the URLs Discord hands a slash command for its
attachments are ephemeral-attachments links that expire after 24
hours, so the bot does NOT rely on them. When a log posts, it
re-uploads each attached screenshot to the evidence channel and uses
that permanent link in the board item. Which channel: the server's
stored evidence channel (set with /ghlog_set_channel), else the
channel the command ran in. There is no per-log channel picker --
the stored channel is the one place evidence goes. Evidence renders
as embedded Markdown images in the body, so the photos show inline
on the board like a hand-made log. Discord caps a command at 10
attachments, so for more photos the logger sends them as chat
messages in the channel instead: the preview has a "Collect
screenshots" button (and /banlog_collect does the same thing if the
button fails) that scans the channel for the logger's recent
screenshots, downloads them, posts them to the evidence channel as a
captioned message plus a thread holding the images, then deletes the
originals from the log channel. Only screenshots sent after the log
started (/banlog ran) are pulled, so old images already in the
channel are never grabbed by mistake. /banlog_update also takes up
to 10 more screenshots to append when a log has more than 10 photos,
and takes a case number as well as a member/user to say which log
to update. /ghlog_backfill_cases scans the whole board for items
whose title has no case number (hand-made logs and logs from before
the case-number flow), gives each one the next free case number, and
rewrites its board title and body to carry it, then reports an embed
with how many were scanned and fixed.

Target board defaults to the test board; switch it with
GITHUB_PROJECT_OWNER / GITHUB_PROJECT_NUMBER when the real board is
wired up. Rows record which board they live on, so an update never
fires at the wrong board after a switch. The board needs the Approval
field (Needs approval / Log approved), a "Needs approval" Status
option, "pending approval" / "approved" tags options, and a Decision
field (Blacklist approved / more info);
utils.github_projects.ensure_approval_setup creates them.

Testing bypass: GHLOG_ALLOW_SELF_APPROVE=1 in .env lets a logger
approve their own log (for testing when only one person is around).
The bot logs a loud warning at startup whenever it is on. REMOVE it
after testing -- it is not meant to stay.
"""

import datetime
import io
import os
import re

import aiohttp
import discord
from discord.ext import commands

from config import GUILD_IDS, admin_required, extra_help, load_json
from data.DB.Storage.storage import (
    delete_ghlog_item,
    get_ghlog_item,
    get_ghlog_item_by_item_id,
    get_ghlog_max_id,
    get_ghlog_settings,
    list_ghlog_items,
    save_ghlog_item,
    save_ghlog_settings,
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
    list_project_items,
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
    "pending approval",
    "approved",
]

# Approval flow markers. A new log posts with Status and Approval both
# set to APPROVAL_PENDING and the tags field set to TAG_PENDING;
# /log_approve flips Approval to APPROVAL_APPROVED, moves Status to
# the category the logger picked, and flips the tag to TAG_APPROVED.
# The bot owns the tags field for the approval state -- the logger does
# not pick a tag at log time. Staff set another tag (for example
# "Blacklist approved") later with /banlog_update.
APPROVAL_FIELD = "Approval"
APPROVAL_PENDING = "Needs approval"
APPROVAL_APPROVED = "Log approved"
TAG_PENDING = "pending approval"
TAG_APPROVED = "approved"

# A single-select field holds only ONE value, so the approval state
# (tags) and a human decision marker cannot share one field. The
# Decision field holds the decision marker ("Blacklist approved",
# "more info") and is set by staff with /banlog_update -- the bot
# never sets it at post or approve time.
DECISION_FIELD = "Decision"
DECISION_CHOICES = [
    "Blacklist approved",
    "more info",
]

# Screenshot collection from chat (the button on the preview, and the
# /banlog_collect fallback command). Discord caps a slash command at
# 10 attachments, but screenshots sent as chat messages have no such
# cap, so the collect flow scans the channel instead. COLLECT_LIMIT
# caps how many it takes in one pass so one tap cannot flood the
# evidence channel; COLLECT_SCAN_LIMIT caps how far back it looks.
COLLECT_LIMIT = 30
COLLECT_SCAN_LIMIT = 100

# Evidence links that look like images render as embedded Markdown
# images in the board body (so the photos show inline on GitHub);
# anything else stays a plain link.
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp")


def _is_image_url(url):
    path = (url or "").split("?", 1)[0].split("#", 1)[0].lower()
    return path.endswith(_IMAGE_EXTS)


def _evidence_lines(evidence_links):
    """Render evidence links for the board body: image URLs as embedded
    Markdown images, anything else as a plain link."""
    lines = []
    for i, link in enumerate(evidence_links, 1):
        if _is_image_url(link):
            lines.append("![Evidence %d](%s)" % (i, link))
        else:
            lines.append("- " + link)
    return lines

# The panel modal takes Status as free text (modals have no dropdowns),
# so typed values are matched forgivingly before posting. Anything still
# unmatched posts with a warning instead of failing.
STATUS_ALIASES = {
    "preds": "Preds",
    "intolerance": "Intolerance e.g. transphobia, racism etc",
    "trolls": "Trolls/Bullies",
    "bullies": "Trolls/Bullies",
    "advertisers": "Advertisers/Scammers",
    "scammers": "Advertisers/Scammers",
    "misc": "Misc",
}


def _self_approve_bypass():
    """Temporary test bypass for the approve-must-be-someone-else rule.

    Set GHLOG_ALLOW_SELF_APPROVE=1 in .env while testing, then REMOVE
    it. The bot logs a loud warning at startup whenever it is on.
    """
    return os.getenv("GHLOG_ALLOW_SELF_APPROVE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


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
        "\n".join(_evidence_lines(evidence_links))
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


def build_preview_embed(title, body, status, tags, prior_items, ticket=None, evidence_channel=None):
    """Ephemeral preview shown before anything posts (never the body raw:
    embeds cap at 4096 chars, so long histories are truncated here).
    The Status shown is the INTENDED category; the item itself posts
    with Status "Needs approval" until a second staff member approves it.
    """
    desc = body if len(body) <= 4000 else body[:4000] + "\n... (full text posts to the board)"
    embed = discord.Embed(
        title="Preview -- about to post to GitHub",
        description=desc,
        color=discord.Color.orange(),
    )
    embed.add_field(name="Title", value=title, inline=False)
    embed.add_field(name="Intended status", value=status or "Not set", inline=True)
    embed.add_field(name="Tags", value=tags or "Not set", inline=True)
    if ticket:
        embed.add_field(name="Ticket", value=ticket, inline=True)
    if evidence_channel:
        embed.add_field(
            name="Evidence images",
            value="Screenshots are re-uploaded to %s when posted, so the "
            "board links are permanent (the links Discord gives a command "
            "expire after 24 hours)." % evidence_channel,
            inline=False,
        )
    embed.add_field(
        name="Approval",
        value="Posts as Needs approval -- a second staff member must "
        "approve it with /log_approve before it moves to its category.",
        inline=False,
    )
    if prior_items:
        lines = [
            "- %s -- %s" % (row.get("action", "?"), _short_date(row.get("created_at")))
            for row in prior_items[:3]
        ]
        embed.add_field(
            name="Already logged for this user", value="\n".join(lines), inline=False
        )
    return embed


async def _resolve_evidence_channel(guild, fallback):
    """Where to re-upload evidence screenshots for a log.

    The server's stored evidence channel (/ghlog_set_channel) wins;
    otherwise the channel the command ran in. There is no per-log
    channel picker -- the stored channel is the one place evidence
    goes. A stored channel id that no longer resolves (the channel
    was deleted, or the bot can no longer see it) falls through to
    the fallback instead of failing the log.
    """
    if guild is not None:
        try:
            settings = await get_ghlog_settings(str(guild.id))
        except Exception:
            settings = {}
        channel_id = (settings or {}).get("evidence_channel_id") or ""
        if channel_id:
            try:
                stored = guild.get_channel(int(channel_id))
            except Exception:
                stored = None
            if stored is not None:
                return stored
    return fallback


async def _rehost_screenshots(channel, shots, caption=None):
    """Re-upload screenshot attachments to a Discord channel so their
    links are permanent.

    The URLs Discord hands a slash command for its attachments are
    ephemeral-attachments links that expire after 24 hours. Re-uploading
    the files to a real channel message gives regular attachment URLs
    that do not expire. shots is a list of (url, filename). Returns
    (new_urls, warnings): new_urls keeps the original URL for any shot
    that could not be re-hosted, so the log still posts. A download or
    upload failure never blocks the log -- it only warns.
    """
    originals = [url for url, _ in shots]
    if not shots:
        return originals, []
    if not channel:
        return originals, [
            "no channel to re-upload the screenshots to; using the "
            "original links (they expire after 24 hours)"
        ]
    new_urls = list(originals)
    warnings = []
    downloaded = []  # (shot index, discord.File)
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for i, (url, filename) in enumerate(shots):
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            raise RuntimeError("HTTP %d" % resp.status)
                        data = await resp.read()
                    downloaded.append(
                        (i, discord.File(io.BytesIO(data), filename=filename))
                    )
                except Exception as exc:
                    warnings.append("could not re-host %s (%s)" % (filename, exc))
        if downloaded:
            msg = await channel.send(
                content=caption, files=[f for _, f in downloaded]
            )
            got = [a.url for a in msg.attachments]
            for k, (i, _) in enumerate(downloaded):
                if k < len(got):
                    new_urls[i] = got[k]
                else:
                    warnings.append(
                        "re-hosted file %d came back without a link" % (i + 1)
                    )
        return new_urls, warnings
    except Exception as exc:
        warnings.append("re-host failed (%s); using the original links" % exc)
        return originals, warnings


def _parse_dt(value):
    """Best-effort parse of a stored datetime.

    The ghlog_items invoke_at column comes back from SQLite as a
    datetime or as an ISO string, depending on the driver, and older
    rows have None. Returns an aware datetime in UTC, or None when
    the value is missing or unparsable (the caller then does not
    filter by time).
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    else:
        try:
            dt = datetime.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt


async def _collect_channel_screenshots(channel, author_id, limit=COLLECT_LIMIT,
                                        exclude_ids=None, after=None):
    """Scan a channel for the logger's recent screenshot attachments.

    Discord caps a slash command at 10 attachments, but screenshots
    sent as chat messages have no such cap, so the collect flow scans
    the channel instead. Looks back COLLECT_SCAN_LIMIT messages for
    image attachments sent by author_id, oldest first, up to limit.
    Messages whose ids are in exclude_ids (already collected on an
    earlier tap) are skipped, so tapping Collect twice only picks up
    the new ones. `after` is when the log started (/banlog ran): only
    screenshots sent after that are pulled, so old images already in
    the channel are never grabbed by mistake. Returns a list of
    (url, filename, message).
    """
    exclude = set(exclude_ids or ())
    found = []
    if channel is None:
        return found
    try:
        async for message in channel.history(limit=COLLECT_SCAN_LIMIT):
            if message.author is None or getattr(message.author, "id", None) != author_id:
                continue
            if message.id in exclude:
                continue
            if after is not None:
                created = _parse_dt(getattr(message, "created_at", None))
                if created is not None and created <= after:
                    continue
            for attachment in getattr(message, "attachments", []) or []:
                if _is_image_url(getattr(attachment, "url", "") or ""):
                    found.append((attachment.url, attachment.filename, message))
    except Exception:
        # History read failed (no permission, or the channel is gone):
        # collecting nothing is a warning for the caller, not a crash.
        return []
    # history() yields newest first; flip so the evidence reads in the
    # order the screenshots were sent, then take the first `limit` (the
    # oldest ones) so a capped pass never skips the earliest shots.
    found.reverse()
    return found[:limit]


async def _post_evidence_thread(evidence_channel, caption, shots, thread_name):
    """Post collected screenshots to the evidence channel as a thread.

    Posts the caption message (what the evidence is for, with the
    time and date) to the evidence channel, makes a thread on it, and
    puts the downloaded screenshots in the thread (up to 10 files per
    message, so more than 10 works). Returns (new_urls, warnings,
    thread_url). If the thread cannot be created, the screenshots go
    straight into the evidence channel as plain messages instead.
    shots is a list of (url, filename).
    """
    warnings = []
    if not shots:
        return [], warnings, None
    if evidence_channel is None:
        return [url for url, _ in shots], [
            "no evidence channel to post the screenshots to; using the "
            "original links (they expire after 24 hours)"
        ], None
    # Download everything first, so a bad link never leaves a thread
    # half full.
    downloaded = []  # (shot index, discord.File)
    originals = [url for url, _ in shots]
    try:
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for i, (url, filename) in enumerate(shots):
                try:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            raise RuntimeError("HTTP %d" % resp.status)
                        data = await resp.read()
                    downloaded.append(
                        (i, discord.File(io.BytesIO(data), filename=filename))
                    )
                except Exception as exc:
                    warnings.append("could not download %s (%s)" % (filename, exc))
    except Exception as exc:
        warnings.append("download failed (%s); using the original links" % exc)
        return originals, warnings, None
    if not downloaded:
        return originals, warnings, None
    new_urls = list(originals)
    try:
        head = await evidence_channel.send(content=caption)
    except Exception as exc:
        warnings.append("could not post to the evidence channel (%s)" % exc)
        return originals, warnings, None
    # The thread holds the images; the caption message stays clean.
    thread = None
    try:
        thread = await head.create_thread(
            name=thread_name[:100], auto_archive_duration=10080
        )
    except Exception as exc:
        warnings.append("could not make a thread (%s); posting in-channel" % exc)
    target = thread if thread is not None else evidence_channel
    # Up to 10 files per message, so a big batch spans several.
    for start in range(0, len(downloaded), 10):
        batch = downloaded[start:start + 10]
        try:
            msg = await target.send(files=[f for _, f in batch])
        except Exception as exc:
            warnings.append("could not post a batch of screenshots (%s)" % exc)
            continue
        got = [a.url for a in msg.attachments]
        for k, (i, _) in enumerate(batch):
            if k < len(got):
                new_urls[i] = got[k]
            else:
                warnings.append(
                    "re-hosted file %d came back without a link" % (i + 1)
                )
    thread_url = None
    if thread is not None:
        thread_url = getattr(thread, "jump_url", None) or getattr(
            thread, "mention", None
        )
    return new_urls, warnings, thread_url


class GHLogConfirmView(discord.ui.View):
    """Preview confirm step shared by /banlog and the panel modal.

    Non-persistent on purpose: it only has to live until staff tap Post
    or Cancel (or the 5-minute timeout disables it). The done flag stops
    a double-tap from posting twice. On Post, the tracking row is
    reserved FIRST (its id is the case/log number, which goes in the
    title and body), then the item posts with Status and Approval both
    "Needs approval". If the post fails, the reserved row is dropped so
    it never shows up as a log that does not exist on the board.

    The "Collect screenshots" button is the chat-message route for
    evidence: the logger sends screenshots as chat messages in the
    channel where /banlog ran (easier on mobile, and no 10-attachment
    cap), then taps Collect. The bot scans that channel for the
    logger's recent screenshots, downloads them, posts them to the
    evidence channel as a captioned message plus a thread holding the
    images, deletes the originals from the log channel, and adds the
    permanent thread links to the preview body. Tapping Collect again
    only picks up screenshots sent since the last tap. /banlog_collect
    does the same thing as a command, in case the button fails.
    """

    def __init__(self, payload):
        super().__init__(timeout=300)
        self.payload = payload
        self.done = False
        self.message = None

    @discord.ui.button(label="Collect screenshots", style=discord.ButtonStyle.primary)
    async def collect_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        p = self.payload
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        if guild is None:
            await interaction.followup.send(
                "Collect only works in a server channel.", ephemeral=True
            )
            return
        invoke_id = p.get("invoke_channel_id")
        invoke_channel = None
        if invoke_id:
            try:
                invoke_channel = guild.get_channel(int(invoke_id))
            except Exception:
                invoke_channel = None
        if invoke_channel is None:
            invoke_channel = getattr(interaction, "channel", None)
        evidence_channel = None
        channel_id = p.get("channel_id")
        if channel_id:
            try:
                evidence_channel = guild.get_channel(int(channel_id))
            except Exception:
                evidence_channel = None
        if evidence_channel is None:
            evidence_channel = await _resolve_evidence_channel(
                guild, getattr(interaction, "channel", None)
            )
        logger_id = p.get("logger_id") or interaction.user.id
        collected_ids = set(p.get("collected_message_ids") or [])
        # Only screenshots sent after the log started (/banlog ran) --
        # old images already in the channel are never grabbed.
        after = _parse_dt(p.get("invoke_at"))
        found = await _collect_channel_screenshots(
            invoke_channel, logger_id, exclude_ids=collected_ids, after=after
        )
        if not found:
            await interaction.followup.send(
                "No new screenshots found in %s from you. Send them as "
                "chat messages in that channel first, then tap Collect "
                "screenshots again."
                % (invoke_channel.mention if invoke_channel else "the channel"),
                ephemeral=True,
            )
            return
        case_hint = p.get("title") or "this log"
        caption = "Evidence images for %s, collected from %s by %s on %s." % (
            case_hint,
            invoke_channel.mention if invoke_channel else "chat",
            interaction.user.display_name,
            _utc_now(),
        )
        shot_pairs = [(url, filename) for url, filename, _ in found]
        new_urls, warnings, thread_url = await _post_evidence_thread(
            evidence_channel,
            caption,
            shot_pairs,
            thread_name="Evidence -- %s" % (p.get("display_name") or "log"),
        )
        # Remove the originals from the log channel now that the
        # permanent copies live in the evidence thread. A failure here
        # (no Manage Messages, or the message is already gone) only
        # warns -- the evidence is already safe. Every message is
        # attempted on its own: one failure must not skip the rest.
        delete_warnings = []
        for _, _, message in found:
            try:
                await message.delete()
            except Exception as exc:
                delete_warnings.append(
                    "could not delete an original (%s) -- the bot needs "
                    "Manage Messages in %s to remove the originals" % (
                        exc,
                        invoke_channel.mention if invoke_channel else "the channel",
                    )
                )
                print(
                    "[GHLOG] Collect: could not delete message %s (%s)"
                    % (getattr(message, "id", "?"), exc)
                )
        for _, _, message in found:
            collected_ids.add(getattr(message, "id", None))
        p["collected_message_ids"] = sorted(
            i for i in collected_ids if i is not None
        )
        # The thread links are permanent, so they go straight into the
        # body as embedded images -- they are NOT re-hosted again on Post.
        add_lines = []
        for i, url in enumerate(new_urls, 1):
            if _is_image_url(url):
                add_lines.append("![Evidence %d](%s)" % (i, url))
            else:
                add_lines.append("- " + url)
        p["body"] = "%s\n\n### Collected evidence -- %s by %s\n%s" % (
            p.get("body") or "",
            _utc_now(),
            interaction.user.display_name,
            "\n".join(add_lines),
        )
        p.setdefault("collected_urls", []).extend(new_urls)
        # Re-render the preview so the logger sees what was collected.
        try:
            prior = await list_ghlog_items(
                int(p["guild_id"]), p.get("user_id")
            ) if p.get("guild_id") else []
        except Exception:
            prior = []
        embed = build_preview_embed(
            p["title"],
            p["body"],
            p.get("status"),
            TAG_PENDING,
            prior,
            ticket=p.get("ticket") or "",
            evidence_channel=(
                evidence_channel.mention if evidence_channel else None
            ),
        )
        try:
            await interaction.edit_original_response(embed=embed, view=self)
        except Exception:
            pass
        note = "Collected %d screenshot(s) into the evidence thread%s." % (
            len(found),
            (" -- %s" % thread_url) if thread_url else "",
        )
        if warnings or delete_warnings:
            note += " Notes: " + " ".join(warnings + delete_warnings)
        await interaction.followup.send(note, ephemeral=True)

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
            row_id = await save_ghlog_item(
                {
                    "guild_id": str(p["guild_id"]),
                    "user_id": str(p["user_id"]),
                    "display_name": p["display_name"],
                    "action": p["action"],
                    "item_id": "",
                    "draft_id": "",
                    "title": p["title"],
                    "body": p["body"],
                    "status": APPROVAL_PENDING,
                    "tags": TAG_PENDING,
                    "intended_status": p.get("status") or "",
                    "ticket": p.get("ticket") or "",
                    "approval": APPROVAL_PENDING,
                    "project_owner": PROJECT_OWNER,
                    "project_number": PROJECT_NUMBER,
                    "logged_by": p["logger_name"],
                    "logged_by_id": str(p.get("logger_id") or ""),
                    # When /banlog ran (not when Post was tapped): the
                    # Collect flow only pulls screenshots sent after this.
                    "invoke_at": p.get("invoke_at"),
                }
            )
        except Exception as exc:
            await interaction.edit_original_response(
                content="Could not reserve a case number for this log: %s" % exc,
                embed=None,
                view=None,
            )
            return
        case_no = row_id
        ticket = p.get("ticket") or ""
        title = "%s -- Case #%d" % (p["title"], case_no)
        body = "Case: #%d\nTicket: %s\n%s" % (case_no, ticket or "--", p["body"])
        # Safety net: the Collect button normally appends a Collected
        # evidence section to the body already, but if that section is
        # missing for any reason the collected screenshots still have
        # to reach the board -- append them here so they are never
        # silently dropped from the log.
        collected_urls = [u for u in (p.get("collected_urls") or []) if u]
        missing = [u for u in collected_urls if u not in body]
        if missing:
            print(
                "[GHLOG] Post fallback: %d collected screenshot(s) were "
                "missing from the body for Case #%d; appending them"
                % (len(missing), case_no)
            )
            add_lines = []
            for i, url in enumerate(missing, 1):
                if _is_image_url(url):
                    add_lines.append("![Evidence %d](%s)" % (i, url))
                else:
                    add_lines.append("- " + url)
            body = "%s\n\n### Collected evidence -- %s by %s\n%s" % (
                body,
                _utc_now(),
                p.get("logger_name") or "",
                "\n".join(add_lines),
            )
        # Re-host attached screenshots so the board links are permanent
        # (the links Discord gives a command expire after 24 hours).
        # The re-hosted URLs replace the originals in the body.
        rehost_warnings = []
        shots = p.get("screenshot_urls") or []
        if shots:
            channel = None
            channel_id = p.get("channel_id")
            if interaction.guild is not None and channel_id:
                try:
                    channel = interaction.guild.get_channel(int(channel_id))
                except Exception:
                    channel = None
            caption = "Evidence images for Case #%d -- %s (%s), logged by %s." % (
                case_no,
                p.get("display_name") or "",
                p.get("user_id") or "",
                p.get("logger_name") or "",
            )
            new_urls, rehost_warnings = await _rehost_screenshots(
                channel, shots, caption=caption
            )
            for old_url, new_url in zip([u for u, _ in shots], new_urls):
                if old_url != new_url:
                    body = body.replace(old_url, new_url)
        try:
            item_id, warnings = await create_logged_case(
                token,
                title,
                body,
                status=APPROVAL_PENDING,
                tags=TAG_PENDING,
                approval=APPROVAL_PENDING,
            )
        except Exception as exc:
            try:
                await delete_ghlog_item(row_id)
            except Exception:
                pass
            await interaction.edit_original_response(
                content="GitHub post failed: %s" % exc, embed=None, view=None
            )
            return
        try:
            await update_ghlog_item(
                row_id, {"item_id": item_id, "title": title, "body": body}
            )
        except Exception:
            # The board post already succeeded; tracking is best-effort
            # and must never turn a success into a failure message.
            pass
        reply = (
            "Case #%d posted to the GitHub project: %s\n"
            "It is waiting in the Needs approval column -- a second staff "
            "member has to approve it with /log_approve before it moves to "
            "its category." % (case_no, BOARD_URL)
        )
        if warnings:
            reply += "\nNotes: " + " ".join(warnings)
        if rehost_warnings:
            reply += (
                "\nEvidence note: " + " ".join(rehost_warnings)
                + " Those images keep their original links, which expire "
                "after 24 hours."
            )
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
    """Log the panel's user to GitHub, prefilled from the last panel ban/kick.

    Discord modals cap at 5 text inputs, so the modal carries Action,
    Reason, Evidence links, Status, and Ticket. Tags are not in the
    modal (set them later with /banlog_update if needed).
    """

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
                label="Ticket",
                style=discord.InputTextStyle.short,
                placeholder="Ticket number, if this log is for a ticket",
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
        ticket = (self.children[4].value or "").strip()
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
        # The Collect button needs to know where to scan (the channel
        # the panel lives in) and where the evidence goes.
        evidence_channel = await _resolve_evidence_channel(
            self.guild, getattr(interaction, "channel", None)
        )
        invoke_channel = getattr(interaction, "channel", None)
        payload = {
            "title": title,
            "body": body,
            "action": action,
            "guild_id": self.guild.id,
            "user_id": self.target_id,
            "display_name": self.target_name,
            "status": status,
            "ticket": ticket,
            "logger_name": interaction.user.display_name,
            "logger_id": interaction.user.id,
            "channel_id": evidence_channel.id if evidence_channel else None,
            "invoke_channel_id": invoke_channel.id if invoke_channel else None,
            # When the panel log started: the Collect flow only pulls
            # screenshots sent after this. (Taken here, when the modal
            # is submitted -- pycord's context has no created_at.)
            "invoke_at": datetime.datetime.now(datetime.timezone.utc),
            "screenshot_urls": [],
            "collected_message_ids": [],
            "collected_urls": [],
            "test_mode": self.panel.test_mode,
        }
        view = GHLogConfirmView(payload)
        await interaction.response.send_message(
            embed=build_preview_embed(
                title, body, status, TAG_PENDING, prior, ticket=ticket
            ),
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
        if _self_approve_bypass():
            print(
                "[GHLOG] WARNING: self-approve bypass is ON "
                "(GHLOG_ALLOW_SELF_APPROVE) -- /log_approve will let a logger "
                "approve their own log. Remove it from .env after testing."
            )

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
        name="ghlog_set_channel",
        description="Set the channel evidence screenshots are re-uploaded to for this server.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Sets the evidence channel for this server: the channel /banlog "
        "re-uploads attached screenshots to, and where collected "
        "screenshots go as a thread, so the board links are permanent. "
        "Pick a channel to set it; pass clear to remove the setting "
        "(logs then use the channel the command runs in); run it with "
        "nothing to see the current setting. There is no per-log channel "
        "picker -- this stored channel is the one place evidence goes. "
        "Manage Server or Administrator only."
    )
    async def ghlog_set_channel(
        self,
        ctx,
        channel: discord.Option(
            discord.TextChannel,
            "Channel to re-upload evidence screenshots to",
            required=False,
            default=None,
        ),
        clear: discord.Option(
            bool,
            "Clear the stored channel (back to the channel the command runs in)",
            required=False,
            default=False,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "ghlog_set_channel", _default_manage_or_admin):
            return
        await ctx.defer(ephemeral=True)
        if channel is not None:
            try:
                await save_ghlog_settings(
                    str(ctx.guild.id),
                    {
                        "evidence_channel_id": str(channel.id),
                        "updated_by": ctx.user.display_name,
                    },
                )
            except Exception as exc:
                return await ctx.followup.send(
                    "Could not save the evidence channel: %s" % exc,
                    ephemeral=True,
                )
            return await ctx.followup.send(
                "Evidence channel set to %s. /banlog will re-upload "
                "screenshots there unless a different channel is picked on "
                "the log itself." % channel.mention,
                ephemeral=True,
            )
        if clear:
            try:
                await save_ghlog_settings(
                    str(ctx.guild.id),
                    {
                        "evidence_channel_id": "",
                        "updated_by": ctx.user.display_name,
                    },
                )
            except Exception as exc:
                return await ctx.followup.send(
                    "Could not clear the evidence channel: %s" % exc,
                    ephemeral=True,
                )
            return await ctx.followup.send(
                "Evidence channel cleared. /banlog will use the channel the "
                "command runs in unless a channel is picked on the log itself.",
                ephemeral=True,
            )
        try:
            settings = await get_ghlog_settings(str(ctx.guild.id))
        except Exception:
            settings = {}
        channel_id = (settings or {}).get("evidence_channel_id") or ""
        if not channel_id:
            return await ctx.followup.send(
                "No evidence channel is set for this server. /banlog uses "
                "the channel the command runs in unless a channel is picked "
                "on the log itself. Run this command with a channel to set one.",
                ephemeral=True,
            )
        stored = None
        try:
            stored = ctx.guild.get_channel(int(channel_id))
        except Exception:
            stored = None
        if stored is None:
            return await ctx.followup.send(
                "The stored evidence channel (<#%s>) no longer exists or "
                "the bot can no longer see it. /banlog will use the channel "
                "the command runs in until a new channel is set here."
                % channel_id,
                ephemeral=True,
            )
        await ctx.followup.send(
            "Evidence channel for this server: %s (set by %s)."
            % (stored.mention, (settings or {}).get("updated_by") or "unknown"),
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
        "evidence links and up to 10 screenshots, a ticket number, and a "
        "short case-history summary. The Status you pick is the category "
        "the log belongs in, but the item posts with Status and Approval "
        "both set to Needs approval and a case number in its title; a "
        "second staff member approves it with /log_approve before it "
        "moves to its category. Nothing posts until you confirm the "
        "preview. Pick a member if they are still in the server, otherwise "
        "paste an ID, mention, or username. For more than 10 screenshots, "
        "send them as chat messages in this channel instead and tap "
        "Collect screenshots on the preview (or run /banlog_collect) -- "
        "the bot posts them to the evidence channel in a thread and "
        "removes the originals. Manage Server or Administrator only."
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
        evidence: discord.Option(
            str, "Evidence links, separated by spaces", required=False, default=None
        ),
        ticket: discord.Option(
            str, "Ticket number for this log", required=False, default=None
        ),
        screenshot: discord.Option(
            discord.Attachment,
            "Screenshot evidence 1 of 10 (its link is added to the case)",
            required=False,
            default=None,
        ),
        screenshot2: discord.Option(
            discord.Attachment,
            "Screenshot evidence 2 of 10",
            required=False,
            default=None,
        ),
        screenshot3: discord.Option(
            discord.Attachment,
            "Screenshot evidence 3 of 10",
            required=False,
            default=None,
        ),
        screenshot4: discord.Option(
            discord.Attachment,
            "Screenshot evidence 4 of 10",
            required=False,
            default=None,
        ),
        screenshot5: discord.Option(
            discord.Attachment,
            "Screenshot evidence 5 of 10",
            required=False,
            default=None,
        ),
        screenshot6: discord.Option(
            discord.Attachment,
            "Screenshot evidence 6 of 10",
            required=False,
            default=None,
        ),
        screenshot7: discord.Option(
            discord.Attachment,
            "Screenshot evidence 7 of 10",
            required=False,
            default=None,
        ),
        screenshot8: discord.Option(
            discord.Attachment,
            "Screenshot evidence 8 of 10",
            required=False,
            default=None,
        ),
        screenshot9: discord.Option(
            discord.Attachment,
            "Screenshot evidence 9 of 10",
            required=False,
            default=None,
        ),
        screenshot10: discord.Option(
            discord.Attachment,
            "Screenshot evidence 10 of 10",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "banlog", _default_manage_or_admin):
            return
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
        shots = [
            s
            for s in (
                screenshot,
                screenshot2,
                screenshot3,
                screenshot4,
                screenshot5,
                screenshot6,
                screenshot7,
                screenshot8,
                screenshot9,
                screenshot10,
            )
            if s is not None
        ]
        shot_pairs = [(s.url, s.filename) for s in shots]
        if shots:
            links = [s.url for s in shots] + links
        # Where the screenshots get re-uploaded for a permanent link:
        # the server's stored evidence channel (/ghlog_set_channel),
        # else the channel this command ran in. There is no per-log
        # channel picker -- the stored channel is the one place
        # evidence goes.
        rehost_channel = await _resolve_evidence_channel(ctx.guild, ctx.channel)
        rehost_channel_id = rehost_channel.id if rehost_channel else None
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
            "ticket": (ticket or "").strip(),
            "logger_name": ctx.user.display_name,
            "logger_id": ctx.user.id,
            "channel_id": rehost_channel_id,
            "invoke_channel_id": ctx.channel.id if ctx.channel else None,
            # When /banlog ran: the Collect flow only pulls screenshots
            # sent after this, so old images in the channel are ignored.
            # (pycord's ApplicationContext has no created_at -- the
            # Interaction does, but the context does not -- so the
            # time is taken here, when the command actually runs.)
            "invoke_at": datetime.datetime.now(datetime.timezone.utc),
            "screenshot_urls": shot_pairs,
            "collected_message_ids": [],
            "collected_urls": [],
            "test_mode": False,
        }
        view = GHLogConfirmView(payload)
        msg = await ctx.followup.send(
            embed=build_preview_embed(
                title,
                body,
                status,
                TAG_PENDING,
                prior,
                ticket=(ticket or "").strip(),
                evidence_channel=(
                    rehost_channel.mention if (shots and rehost_channel) else None
                ),
            ),
            view=view,
            ephemeral=True,
        )
        try:
            view.message = msg
        except Exception:
            pass

    @discord.slash_command(
        name="log_approve",
        description="Approve a pending GitHub log and move it to its category.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Approves a log that is waiting in the Needs approval column: "
        "moves it to the category the logger picked, flips its Approval "
        "field to Log approved and its tag to approved, and appends an "
        "approval note to the board item. There is no category override "
        "here on purpose -- approve always moves it to the category the "
        "logger logged it under, so it lands in the right spot. If the "
        "category itself is wrong, fix it first with /banlog_update. "
        "Give a case number, or a member/user to approve their most recent "
        "pending log. The approver must be a different staff member than "
        "the logger (unless the temporary GHLOG_ALLOW_SELF_APPROVE test "
        "bypass is on). Manage Server or Administrator only."
    )
    async def log_approve(
        self,
        ctx,
        case: discord.Option(
            int, "Case/log number to approve", required=False, default=None
        ),
        member: discord.Option(
            discord.Member,
            "Member whose most recent pending log to approve",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "User ID, mention, or username (most recent pending log)",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "log_approve", _default_manage_or_admin):
            return
        if case is None and member is None and not user_id:
            return await ctx.respond(
                "Give a case number, or a member/user to approve their "
                "most recent pending log.",
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
        row = None
        if case is not None:
            try:
                row = await get_ghlog_item(case)
            except Exception:
                row = None
            if row is None:
                return await ctx.followup.send(
                    "No log on file with case number #%d." % case,
                    ephemeral=True,
                )
            if str(row.get("guild_id")) != str(ctx.guild.id):
                return await ctx.followup.send(
                    "Case #%d belongs to a different server." % case,
                    ephemeral=True,
                )
        else:
            target_id, display = await self._resolve_target(ctx, member, user_id)
            if display is None:
                return await ctx.followup.send(
                    "Pick a member, or give a user ID, mention, or username I can find.",
                    ephemeral=True,
                )
            try:
                rows = await list_ghlog_items(ctx.guild.id, target_id)
            except Exception:
                rows = []
            pending = [r for r in rows if (r.get("approval") or "") == APPROVAL_PENDING]
            if not pending:
                return await ctx.followup.send(
                    "No pending log for %s -- nothing waiting for approval." % display,
                    ephemeral=True,
                )
            row = pending[0]
        if row.get("project_owner") != PROJECT_OWNER or row.get("project_number") != PROJECT_NUMBER:
            return await ctx.followup.send(
                "That item lives on the %s board (project %s), but the bot is "
                "now pointed at %s project %s. Switch the target back to "
                "approve it."
                % (
                    row.get("project_owner"),
                    row.get("project_number"),
                    PROJECT_OWNER,
                    PROJECT_NUMBER,
                ),
                ephemeral=True,
            )
        if (row.get("approval") or "") != APPROVAL_PENDING:
            return await ctx.followup.send(
                "Case #%d is not waiting for approval (approval: %s)."
                % (row["id"], row.get("approval") or "already final"),
                ephemeral=True,
            )
        bypass = _self_approve_bypass()
        logger_id = (row.get("logged_by_id") or "").strip()
        if logger_id:
            same_person = str(ctx.user.id) == logger_id
        else:
            same_person = (row.get("logged_by") or "").strip().lower() == (
                ctx.user.display_name.strip().lower()
            )
        if same_person and not bypass:
            return await ctx.followup.send(
                "You logged Case #%d -- a different staff member has to "
                "approve it." % row["id"],
                ephemeral=True,
            )
        # Approve always moves the item to the category the logger
        # picked (intended_status). There is no override here on
        # purpose: an override once sent a log to the wrong column
        # instead of the logger's category. If the category itself is
        # wrong, fix it first with /banlog_update.
        dest = row.get("intended_status") or ""
        if not dest:
            return await ctx.followup.send(
                "Case #%d has no category logged for it -- set one with "
                "/banlog_update first, then approve it." % row["id"],
                ephemeral=True,
            )
        try:
            project_id, fields = await get_project_fields(token)
            for field_name, option_name in (
                ("Status", dest),
                (APPROVAL_FIELD, APPROVAL_APPROVED),
                ("tags", TAG_APPROVED),
            ):
                field = fields.get(field_name)
                option_id = field["options"].get(option_name) if field else None
                if not option_id:
                    return await ctx.followup.send(
                        "Board %s has no option %r -- check the board setup."
                        % (field_name, option_name),
                        ephemeral=True,
                    )
                await set_single_select(
                    token, project_id, row["item_id"], field["id"], option_id
                )
            draft_id = row.get("draft_id") or await resolve_draft_issue_id(
                token, row["item_id"]
            )
            new_body = "%s\n\n### Approved -- %s by %s\nMoved to %s." % (
                row.get("body") or "",
                _utc_now(),
                ctx.user.display_name,
                dest,
            )
            await update_draft_issue(token, draft_id, row["title"], new_body)
            await update_ghlog_item(
                row["id"],
                {
                    "status": dest,
                    "approval": APPROVAL_APPROVED,
                    "tags": TAG_APPROVED,
                    "body": new_body,
                    "draft_id": draft_id,
                },
            )
        except Exception as exc:
            return await ctx.followup.send(
                "Approve failed: %s (any fields applied before the failure stay applied)."
                % exc,
                ephemeral=True,
            )
        reply = (
            "Approved Case #%d -- moved to %s and marked Log approved: %s"
            % (row["id"], dest, BOARD_URL)
        )
        if bypass and same_person:
            reply += (
                "\n(Note: the self-approve bypass is ON for testing -- "
                "remove GHLOG_ALLOW_SELF_APPROVE from .env when testing is done.)"
            )
        await ctx.followup.send(reply, ephemeral=True)

    @discord.slash_command(
        name="banlog_update",
        description="Update a logged case on the GitHub board.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Finds a board item and changes its Status and/or tags, sets the "
        "Decision field (for example Blacklist approved -- the tags field "
        "holds only one value, so the decision marker lives in its own "
        "field), appends a dated note to its body, and/or appends up to "
        "10 more screenshots (for logs with more than 10 photos in total "
        "-- the new screenshots are re-uploaded to the server's evidence "
        "channel so their board links are permanent). Give a case number "
        "to update that log, or a member/user to update their most recent "
        "log. Give at least one of status, tags, decision, note, or a "
        "screenshot. A case still waiting for approval keeps its Status "
        "until /log_approve moves it; tags, decision, notes, and "
        "screenshots can still be updated here. Only touches items logged "
        "while the bot pointed at the current board. Manage Server or "
        "Administrator only."
    )
    async def banlog_update(
        self,
        ctx,
        case: discord.Option(
            int, "Case/log number to update", required=False, default=None
        ),
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
        decision: discord.Option(
            str,
            "Decision marker (Blacklist approved, more info)",
            required=False,
            default=None,
            choices=DECISION_CHOICES,
        ),
        note: discord.Option(
            str, "Note to append to the board item", required=False, default=None
        ),
        screenshot: discord.Option(
            discord.Attachment,
            "Screenshot to add 1 of 10",
            required=False,
            default=None,
        ),
        screenshot2: discord.Option(
            discord.Attachment,
            "Screenshot to add 2 of 10",
            required=False,
            default=None,
        ),
        screenshot3: discord.Option(
            discord.Attachment,
            "Screenshot to add 3 of 10",
            required=False,
            default=None,
        ),
        screenshot4: discord.Option(
            discord.Attachment,
            "Screenshot to add 4 of 10",
            required=False,
            default=None,
        ),
        screenshot5: discord.Option(
            discord.Attachment,
            "Screenshot to add 5 of 10",
            required=False,
            default=None,
        ),
        screenshot6: discord.Option(
            discord.Attachment,
            "Screenshot to add 6 of 10",
            required=False,
            default=None,
        ),
        screenshot7: discord.Option(
            discord.Attachment,
            "Screenshot to add 7 of 10",
            required=False,
            default=None,
        ),
        screenshot8: discord.Option(
            discord.Attachment,
            "Screenshot to add 8 of 10",
            required=False,
            default=None,
        ),
        screenshot9: discord.Option(
            discord.Attachment,
            "Screenshot to add 9 of 10",
            required=False,
            default=None,
        ),
        screenshot10: discord.Option(
            discord.Attachment,
            "Screenshot to add 10 of 10",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "banlog_update", _default_manage_or_admin):
            return
        if case is None and member is None and not user_id:
            return await ctx.respond(
                "Give a case number, or a member/user to update their "
                "most recent log.",
                ephemeral=True,
            )
        shots = [
            s
            for s in (
                screenshot,
                screenshot2,
                screenshot3,
                screenshot4,
                screenshot5,
                screenshot6,
                screenshot7,
                screenshot8,
                screenshot9,
                screenshot10,
            )
            if s is not None
        ]
        if not status and not tags and not decision and not note and not shots:
            return await ctx.respond(
                "Give at least one of status, tags, decision, note, or a screenshot to update.",
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
        # A case number picks the log directly; otherwise the most
        # recent log for the member/user.
        row = None
        if case is not None:
            try:
                row = await get_ghlog_item(case)
            except Exception:
                row = None
            if row is None:
                return await ctx.followup.send(
                    "No log on file with case number #%d." % case,
                    ephemeral=True,
                )
            if str(row.get("guild_id")) != str(ctx.guild.id):
                return await ctx.followup.send(
                    "Case #%d belongs to a different server." % case,
                    ephemeral=True,
                )
            display = row.get("display_name") or ""
            target_id = row.get("user_id") or ""
        else:
            target_id, display = await self._resolve_target(ctx, member, user_id)
            if display is None:
                return await ctx.followup.send(
                    "Pick a member, or give a user ID, mention, or username I can find.",
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
        warnings = []
        if status and (row.get("approval") or "") == APPROVAL_PENDING:
            if not tags and not decision and not note and not shots:
                return await ctx.followup.send(
                    "That case is still waiting for approval -- use "
                    "/log_approve to move it to its category. Tags, decision, "
                    "notes, and screenshots can still be updated here.",
                    ephemeral=True,
                )
            warnings.append(
                "Status was not changed: this case is still waiting for "
                "approval (use /log_approve)."
            )
            status = None
        try:
            project_id, fields = await get_project_fields(token)
            updates = {}
            for field_name, option_name in (
                ("Status", status),
                ("tags", tags),
                (DECISION_FIELD, decision),
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
            # The Decision field is a board-only marker (no column in
            # ghlog_items), so it is set on the board and reported, but
            # not stored in the row.
            if status:
                updates["status"] = status
            if tags:
                updates["tags"] = tags
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
            if shots:
                # Re-host the new screenshots so their board links are
                # permanent, then append them to the item's body. The
                # channel is the server's stored evidence channel, else
                # this channel (no per-log picker).
                rehost_channel = await _resolve_evidence_channel(
                    ctx.guild, ctx.channel
                )
                caption = "Additional evidence images for Case #%d -- %s (%s), added by %s." % (
                    row["id"],
                    display,
                    target_id,
                    ctx.user.display_name,
                )
                shot_pairs = [(s.url, s.filename) for s in shots]
                new_urls, rehost_warnings = await _rehost_screenshots(
                    rehost_channel, shot_pairs, caption=caption
                )
                warnings.extend(rehost_warnings)
                add_lines = []
                for i, url in enumerate(new_urls, 1):
                    if _is_image_url(url):
                        add_lines.append("![Additional evidence %d](%s)" % (i, url))
                    else:
                        add_lines.append("- " + url)
                base_body = updates.get("body", row.get("body") or "")
                new_body = "%s\n\n### Additional evidence -- %s by %s\n%s" % (
                    base_body,
                    _utc_now(),
                    ctx.user.display_name,
                    "\n".join(add_lines),
                )
                draft_id = (
                    updates.get("draft_id")
                    or row.get("draft_id")
                    or await resolve_draft_issue_id(token, row["item_id"])
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
        if decision:
            changed.append("Decision -> %s" % decision)
        if note:
            changed.append("note appended")
        if shots:
            changed.append("%d screenshot(s) appended" % len(shots))
        reply = "Updated %s's board item (%s): %s" % (display, BOARD_URL, ", ".join(changed))
        if warnings:
            reply += "\nNotes: " + " ".join(warnings)
        await ctx.followup.send(reply, ephemeral=True)

    @discord.slash_command(
        name="banlog_collect",
        description="Collect screenshots sent in this channel into a log's evidence thread.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "The button-free way to add screenshots to a log: send the "
        "screenshots as chat messages in this channel, then run this "
        "command. It scans this channel for your recent screenshots, "
        "downloads them, posts them to the server's evidence channel as "
        "a captioned message plus a thread holding the images, deletes "
        "the originals from this channel, and appends the permanent "
        "thread links to the board item as Additional evidence. Give a "
        "case number, or a member/user to use their most recent log. "
        "Use it when the Collect screenshots button on the preview "
        "fails, or after a log has already posted. Manage Server or "
        "Administrator only."
    )
    async def banlog_collect(
        self,
        ctx,
        case: discord.Option(
            int, "Case/log number to attach the screenshots to",
            required=False, default=None
        ),
        member: discord.Option(
            discord.Member,
            "Member whose most recent log to attach to",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "User ID, mention, or username (most recent log)",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "banlog_collect", _default_manage_or_admin):
            return
        if case is None and member is None and not user_id:
            return await ctx.respond(
                "Give a case number, or a member/user to use their most "
                "recent log.",
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
        row = None
        if case is not None:
            try:
                row = await get_ghlog_item(case)
            except Exception:
                row = None
            if row is None:
                return await ctx.followup.send(
                    "No log on file with case number #%d." % case,
                    ephemeral=True,
                )
            if str(row.get("guild_id")) != str(ctx.guild.id):
                return await ctx.followup.send(
                    "Case #%d belongs to a different server." % case,
                    ephemeral=True,
                )
        else:
            target_id, display = await self._resolve_target(ctx, member, user_id)
            if display is None:
                return await ctx.followup.send(
                    "Pick a member, or give a user ID, mention, or username I can find.",
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
                "collect for it."
                % (
                    row.get("project_owner"),
                    row.get("project_number"),
                    PROJECT_OWNER,
                    PROJECT_NUMBER,
                ),
                ephemeral=True,
            )
        # Only screenshots sent after the log started (/banlog ran) --
        # the row records when the log was invoked, so old images
        # already in the channel are never grabbed.
        after = _parse_dt(row.get("invoke_at"))
        found = await _collect_channel_screenshots(
            ctx.channel, ctx.user.id, after=after
        )
        if not found:
            return await ctx.followup.send(
                "No screenshots found in %s from you. Send them as chat "
                "messages in this channel first, then run /banlog_collect "
                "again." % (ctx.channel.mention if ctx.channel else "this channel"),
                ephemeral=True,
            )
        evidence_channel = await _resolve_evidence_channel(ctx.guild, ctx.channel)
        display = row.get("display_name") or ""
        caption = "Evidence images for Case #%d -- %s (%s), collected from %s by %s on %s." % (
            row["id"],
            display,
            row.get("user_id") or "",
            ctx.channel.mention if ctx.channel else "chat",
            ctx.user.display_name,
            _utc_now(),
        )
        shot_pairs = [(url, filename) for url, filename, _ in found]
        new_urls, warnings, thread_url = await _post_evidence_thread(
            evidence_channel,
            caption,
            shot_pairs,
            thread_name="Case #%d evidence -- %s" % (row["id"], display),
        )
        delete_warnings = []
        for _, _, message in found:
            try:
                await message.delete()
            except Exception as exc:
                delete_warnings.append(
                    "could not delete an original (%s) -- the bot needs "
                    "Manage Messages in %s to remove the originals" % (
                        exc,
                        ctx.channel.mention if ctx.channel else "the channel",
                    )
                )
                print(
                    "[GHLOG] banlog_collect: could not delete message %s (%s)"
                    % (getattr(message, "id", "?"), exc)
                )
        # Append the permanent thread links to the board item, same as
        # /banlog_update's screenshot append.
        try:
            add_lines = []
            for i, url in enumerate(new_urls, 1):
                if _is_image_url(url):
                    add_lines.append("![Additional evidence %d](%s)" % (i, url))
                else:
                    add_lines.append("- " + url)
            new_body = "%s\n\n### Additional evidence -- %s by %s\n%s" % (
                row.get("body") or "",
                _utc_now(),
                ctx.user.display_name,
                "\n".join(add_lines),
            )
            draft_id = row.get("draft_id") or await resolve_draft_issue_id(
                token, row["item_id"]
            )
            await update_draft_issue(token, draft_id, row["title"], new_body)
            await update_ghlog_item(
                row["id"], {"body": new_body, "draft_id": draft_id}
            )
        except Exception as exc:
            warnings.append("could not append the links to the board item (%s)" % exc)
        reply = "Collected %d screenshot(s) for Case #%d into the evidence thread%s." % (
            len(found),
            row["id"],
            (" -- %s" % thread_url) if thread_url else "",
        )
        if warnings or delete_warnings:
            reply += " Notes: " + " ".join(warnings + delete_warnings)
        await ctx.followup.send(reply, ephemeral=True)

    @discord.slash_command(
        name="ghlog_backfill_cases",
        description="Give a case number to board logs that do not have one.",
        guild_ids=GUILD_IDS,
    )
    @extra_help(
        "Scans the whole GitHub ban-log board for items whose title has "
        "no case number (hand-made logs and logs from before the "
        "case-number flow), gives each one the next free case number, "
        "and rewrites its board title and body to carry it. A log that "
        "already has a tracked row keeps its original case number "
        "instead of getting a new one. Replies with an embed saying how "
        "many items were scanned and how many got a case number. "
        "Manage Server or Administrator only."
    )
    async def ghlog_backfill_cases(self, ctx):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "ghlog_backfill_cases", _default_manage_or_admin):
            return
        await ctx.defer(ephemeral=True)
        token = os.getenv("GITHUB_PROJECT_TOKEN")
        if not token:
            return await ctx.followup.send(
                "GitHub token is not set. Add GITHUB_PROJECT_TOKEN to .env "
                "and restart the bot, then try again.",
                ephemeral=True,
            )
        try:
            items = await list_project_items(token)
        except Exception as exc:
            return await ctx.followup.send(
                "Could not read the board: %s" % exc, ephemeral=True
            )
        # Case numbers already on the board, so a new one never
        # collides with a title that already has one.
        have_case = set()
        for item in items:
            match = re.search(r"Case #(\d+)", item.get("title") or "")
            if match:
                have_case.add(int(match.group(1)))
        try:
            max_row_id = await get_ghlog_max_id()
        except Exception:
            max_row_id = 0
        next_case = max(max(have_case) if have_case else 0, max_row_id) + 1
        scanned = len(items)
        already = 0
        fixed = 0
        not_draft = 0
        failed = 0
        fixed_lines = []
        fail_lines = []
        for item in items:
            title = item.get("title") or ""
            if re.search(r"Case #(\d+)", title):
                already += 1
                continue
            if not item.get("is_draft") or not item.get("draft_id"):
                not_draft += 1
                fail_lines.append(
                    "%s -- not a draft issue, cannot rewrite its title"
                    % (title or item.get("item_id") or "?")
                )
                continue
            # Name + user id from the title ("Name (123456789)"); a
            # hand-made log may have just a name.
            user_match = re.search(r"\((\d+)\)", title)
            user_id = user_match.group(1) if user_match else ""
            display = re.sub(r"\s*\(\d+\)\s*$", "", title).strip() or title
            body = item.get("body") or ""
            ticket_match = re.search(r"Ticket:\s*(\S+)", body)
            ticket = ticket_match.group(1) if ticket_match else ""
            action_match = re.search(r"Action:\s*([^\n]+)", body)
            action = action_match.group(1).strip() if action_match else ""
            fields = item.get("fields") or {}
            status = fields.get("Status") or ""
            # A log that already has a tracked row keeps its original
            # case number instead of getting a new one.
            try:
                existing = await get_ghlog_item_by_item_id(item["item_id"])
            except Exception:
                existing = None
            if existing is not None:
                case_no = existing["id"]
            else:
                case_no = next_case
                next_case += 1
            new_title = "%s -- Case #%d" % (title, case_no)
            new_body = body
            if not new_body.startswith("Case:"):
                new_body = "Case: #%d\n%s" % (case_no, new_body)
            try:
                await update_draft_issue(
                    token, item["draft_id"], new_title, new_body
                )
            except Exception as exc:
                failed += 1
                fail_lines.append(
                    "%s -- could not rewrite the board item (%s)"
                    % (display, exc)
                )
                continue
            # Track it, so /banlog_update, /log_approve and
            # /banlog_collect can find it by case number.
            try:
                if existing is not None:
                    await update_ghlog_item(
                        existing["id"],
                        {"title": new_title, "body": new_body,
                         "draft_id": item["draft_id"]},
                    )
                else:
                    await save_ghlog_item(
                        {
                            "id": case_no,
                            "guild_id": str(ctx.guild.id),
                            "user_id": user_id,
                            "display_name": display,
                            "action": action,
                            "item_id": item["item_id"],
                            "draft_id": item["draft_id"],
                            "title": new_title,
                            "body": new_body,
                            "status": status,
                            "tags": fields.get("tags") or "",
                            "intended_status": (
                                "" if status == APPROVAL_PENDING else status
                            ),
                            "ticket": ticket,
                            "approval": fields.get("Approval") or "",
                            "project_owner": PROJECT_OWNER,
                            "project_number": PROJECT_NUMBER,
                            "logged_by": "backfill",
                            "logged_by_id": "",
                            "invoke_at": None,
                        }
                    )
            except Exception as exc:
                failed += 1
                fail_lines.append(
                    "%s -- board updated to Case #%d but tracking failed (%s)"
                    % (display, case_no, exc)
                )
                continue
            fixed += 1
            fixed_lines.append("Case #%d -- %s" % (case_no, display))
        embed = discord.Embed(
            title="Ban-log case backfill",
            description=(
                "Scanned the GitHub board for logs without a case number "
                "and gave each one the next free number."
            ),
            color=discord.Color.green(),
        )
        embed.add_field(name="Scanned", value=str(scanned), inline=True)
        embed.add_field(name="Already had a case number", value=str(already), inline=True)
        embed.add_field(name="Fixed (case numbers added)", value=str(fixed), inline=True)
        if not_draft:
            embed.add_field(
                name="Skipped (not a draft issue)", value=str(not_draft), inline=True
            )
        if failed:
            embed.add_field(name="Failed", value=str(failed), inline=True)
        if fixed_lines:
            shown = fixed_lines[:10]
            text = "\n".join(shown)
            if len(fixed_lines) > 10:
                text += "\n+%d more" % (len(fixed_lines) - 10)
            embed.add_field(name="Case numbers added", value=text, inline=False)
        if fail_lines:
            shown = fail_lines[:5]
            text = "\n".join(shown)
            if len(fail_lines) > 5:
                text += "\n+%d more" % (len(fail_lines) - 5)
            embed.add_field(name="Problems", value=text, inline=False)
        await ctx.followup.send(embed=embed, ephemeral=True)

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
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "banlog_delete", _default_manage_or_admin):
            return
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
