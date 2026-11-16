"""Logs message sends (cached), edits, and deletes."""
import asyncio
import io

import aiohttp
import discord
from discord.ext import commands

from .base import BaseLogger
from .config import MESSAGE, EV_MESSAGE_EDIT, EV_MESSAGE_DELETE, EV_BULK_DELETE
from .database import db
from .embeds import LoggerEmbed, user_line

# Attachment rescue: Discord's copy of a deleted message's attachment
# URLs dies ~30-60 minutes after the delete, so the delete-log links go
# dead. The rescue downloads the attachments immediately (while the
# URLs are still alive) and re-uploads them into a thread on the log
# message, where they live permanently for mods.
_DOWNLOAD_TIMEOUT_SECONDS = 30
_THREAD_NAME_MAX = 100  # Discord's thread-name limit
_FILES_PER_MESSAGE = 10  # Discord's per-message attachment cap
# Files are held in memory between download and upload, so the total
# bytes held at once is capped. 100 MB is generous for the normal case
# (screenshots are usually well under 1 MB each) while still bounding
# memory; the per-file guild filesize_limit check still applies on
# top of it. Files past the cap are skipped with a note.
_RESCUE_TOTAL_BYTES_MAX = 100 * 1024 * 1024


def _fmt_size(n):
    """Human-readable byte size for skip notes."""
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return "%d %s" % (n, unit)
        n //= 1024
    return "%d TB" % n


def _thread_name(display_name, author_id, when):
    """Thread name: '<display> (<id>) — <YYYY-MM-DD HH:MM UTC>'.

    Discord caps thread names at 100 characters, so the display name is
    truncated to fit; the id is never cut. When is the deletion time
    (UTC -- Discord has no per-guild timezone, so the label is explicit).
    """
    ts = when.strftime("%Y-%m-%d %H:%M UTC")
    if author_id is not None:
        suffix = " (%s) — %s" % (author_id, ts)
    else:
        suffix = " — %s" % ts
    name = (display_name or "Unknown").strip() or "Unknown"
    room = _THREAD_NAME_MAX - len(suffix)
    if len(name) > room:
        name = name[:max(room, 1)].rstrip()
    return "%s%s" % (name, suffix)


def _archive_duration(guild):
    """Longest thread auto-archive the guild's boost tier allows.

    1 week needs tier 3, 3 days needs tier 2; everyone gets 1 day.
    """
    tier = getattr(guild, "premium_tier", 0) or 0
    if tier >= 3:
        return 10080
    if tier >= 2:
        return 4320
    return 1440


class MessageLogger(BaseLogger):
    """Caches every guild message; logs edits and deletes."""

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        # P1-25: this fires on EVERY message, so the cache write runs
        # in a worker thread -- a disk write here used to block the
        # gateway loop on every single message.
        await asyncio.to_thread(db.save_message, message)

    @commands.Cog.listener()
    async def on_message_delete(self, message):
        if message.guild is None:
            return
        if not db.is_enabled(message.guild.id, EV_MESSAGE_DELETE):
            return
        cached = db.get_message(message.id)
        content = message.content or (cached["content"] if cached else "")
        author_name = str(message.author) if message.author else (
            cached["author_name"] if cached else "Unknown"
        )
        author_id = message.author.id if message.author else (
            cached["author_id"] if cached else None
        )

        # The user line keeps the cached name when the author object
        # is gone (uncached delete): "Name (<@id> (id))".
        if message.author is not None:
            who = user_line(message.author)
        elif author_id is not None:
            who = f"{author_name} (<@{author_id}> ({author_id}))"
        else:
            who = author_name
        sent_line = ""
        if message.created_at:
            sent_line = (
                "\n**Sent:** "
                f"{discord.utils.format_dt(message.created_at, style='F')}"
            )
        embed = LoggerEmbed.base(
            "🗑 Message Deleted",
            LoggerEmbed.RED,
            description=(
                f"**User:** {who}\n"
                f"**Channel:** {message.channel.mention}"
                f"{sent_line}"
            ),
        )
        if message.author:
            LoggerEmbed.author(embed, message.author)
        else:
            embed.set_author(name=author_name)
        LoggerEmbed.field(embed, "Content", content or "*No message content.*")
        attachments = message.attachments or []
        if attachments:
            lines = [f"📎 [{a.filename}]({a.url})" for a in attachments]
            LoggerEmbed.field(embed, "Attachments", "\n".join(lines))
            for a in attachments:
                if (a.content_type or "").startswith("image"):
                    embed.set_image(url=a.url)
                    break
        LoggerEmbed.finalize(embed)

        log_msg = await self.send(message.guild, MESSAGE, embed)
        # P1-25: cache delete runs in a worker thread, like the other
        # Logger writes, so it never blocks the gateway loop.
        await asyncio.to_thread(db.delete_message, message.id)
        if log_msg is not None and attachments:
            try:
                await self._rescue_attachments(
                    log_msg, message, attachments, author_name, author_id
                )
            except Exception as exc:
                print("[WARN] [LOGGER] attachment rescue failed: %r" % (exc,))

    async def _rescue_attachments(self, log_message, message, attachments,
                                  author_name, author_id):
        """Re-upload a deleted message's attachments into a thread on the
        log message, so they survive after Discord's copy of the
        original attachment URLs expires.

        Bot-posted attachments are never rescued: they are system /
        regenerable content (e.g. a RaidProtect captcha), not user
        content mods need preserved. All attachments are downloaded
        FIRST and the thread is only created when at least one file
        actually came down -- if every download fails or is skipped,
        no (empty) thread is made. Skip notes only ever appear inside
        a thread that has at least one real file.

        Never raises: a thread-creation failure only logs a warning, and
        each file is handled independently so one bad file can't stop
        the rest.
        """
        # Bot authors (RaidProtect captchas, etc.): no thread, no
        # downloads, nothing. The delete log embed itself still posts
        # -- that is the Logger's normal delete logging, untouched.
        if message.author is not None and getattr(
            message.author, "bot", False
        ):
            return
        guild = message.guild
        if message.author is not None:
            display_name = (
                getattr(message.author, "display_name", None)
                or getattr(message.author, "name", None)
                or str(message.author)
            )
        else:
            display_name = author_name

        # --- download phase: everything first. The thread is only
        # created below, once at least one file is in hand. ---
        limit = guild.filesize_limit
        files = []
        skipped = []
        total_bytes = 0
        try:
            timeout = aiohttp.ClientTimeout(total=_DOWNLOAD_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                for a in attachments:
                    if a.size and a.size > limit:
                        skipped.append(
                            "Skipped %s (%s) — too large to re-upload"
                            % (a.filename, _fmt_size(a.size))
                        )
                        continue
                    if a.size and total_bytes + a.size > _RESCUE_TOTAL_BYTES_MAX:
                        skipped.append(
                            "Skipped %s — total rescue size limit (%s) reached"
                            % (a.filename, _fmt_size(_RESCUE_TOTAL_BYTES_MAX))
                        )
                        continue
                    try:
                        async with session.get(a.url) as resp:
                            if resp.status != 200:
                                raise RuntimeError("HTTP %d" % resp.status)
                            data = await resp.read()
                        if len(data) > limit:
                            skipped.append(
                                "Skipped %s (%s) — too large to re-upload"
                                % (a.filename, _fmt_size(len(data)))
                            )
                            continue
                        if total_bytes + len(data) > _RESCUE_TOTAL_BYTES_MAX:
                            skipped.append(
                                "Skipped %s — total rescue size limit (%s) reached"
                                % (a.filename, _fmt_size(_RESCUE_TOTAL_BYTES_MAX))
                            )
                            continue
                        total_bytes += len(data)
                        files.append(
                            discord.File(io.BytesIO(data), filename=a.filename)
                        )
                    except Exception as exc:
                        skipped.append(
                            "Skipped %s — download failed (%s)"
                            % (a.filename, exc)
                        )
        except Exception as exc:
            # Session-level failure: everything not already downloaded
            # is a skip.
            have = {f.filename for f in files}
            for a in attachments:
                if a.filename not in have and not any(
                    a.filename in line for line in skipped
                ):
                    skipped.append(
                        "Skipped %s — download failed (%s)"
                        % (a.filename, exc)
                    )

        if not files:
            # Nothing actually came down, so there is nothing to put
            # in a thread -- do not create an empty one.
            print(
                "[WARN] [LOGGER] attachment rescue: nothing to post for "
                "message %s, no thread created (%s)"
                % (message.id,
                   "; ".join(skipped) if skipped else "no files downloaded")
            )
            return

        # --- upload phase: a thread only exists because files came down.
        name = _thread_name(
            display_name, author_id, discord.utils.utcnow()
        )
        try:
            thread = await log_message.create_thread(
                name=name, auto_archive_duration=_archive_duration(guild)
            )
        except discord.HTTPException:
            # The tier-based duration was rejected; fall back to the
            # channel default.
            try:
                thread = await log_message.create_thread(name=name)
            except Exception as exc:
                print(
                    "[WARN] [LOGGER] attachment rescue: could not create "
                    "thread: %r" % (exc,)
                )
                return
        except Exception as exc:
            print(
                "[WARN] [LOGGER] attachment rescue: could not create "
                "thread: %r" % (exc,)
            )
            return

        sent_at = (
            discord.utils.format_dt(message.created_at, style="F")
            if message.created_at else "unknown time"
        )
        try:
            await thread.send(
                "Attachments rescued from a deleted message by %s in %s "
                "— original message sent %s."
                % (display_name, message.channel.mention, sent_at)
            )
        except Exception as exc:
            print(
                "[WARN] [LOGGER] attachment rescue: could not post "
                "context message: %r" % (exc,)
            )

        for i in range(0, len(files), _FILES_PER_MESSAGE):
            batch = files[i:i + _FILES_PER_MESSAGE]
            try:
                await thread.send(files=batch)
            except Exception as exc:
                for f in batch:
                    skipped.append(
                        "Skipped %s — upload failed (%s)"
                        % (f.filename, exc)
                    )

        if skipped:
            try:
                await thread.send("\n".join(skipped))
            except Exception as exc:
                print(
                    "[WARN] [LOGGER] attachment rescue: could not post "
                    "skip note: %r" % (exc,)
                )

    @commands.Cog.listener()
    async def on_message_edit(self, before, after):
        if before.author.bot or before.guild is None:
            return
        if not db.is_enabled(before.guild.id, EV_MESSAGE_EDIT):
            return
        if before.content == after.content:
            return

        embed = LoggerEmbed.base(
            "✏ Message Edited",
            LoggerEmbed.BLUE,
            description=(
                f"**User:** {user_line(before.author)}\n"
                f"**Channel:** {before.channel.mention}\n"
                f"**Jump:** [Go to message]({after.jump_url})"
            ),
        )
        LoggerEmbed.author(embed, before.author)
        LoggerEmbed.field(embed, "Before", before.content or "*Empty*")
        LoggerEmbed.field(embed, "After", after.content or "*Empty*")
        LoggerEmbed.finalize(embed)

        await self.send(before.guild, MESSAGE, embed)
        # P1-25: cache write in a worker thread (see on_message).
        await asyncio.to_thread(db.save_message, after)

    @commands.Cog.listener()
    async def on_raw_bulk_message_delete(self, payload):
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        if not db.is_enabled(guild.id, EV_BULK_DELETE):
            return
        channel = guild.get_channel(payload.channel_id)
        embed = LoggerEmbed.base(
            "🧹 Bulk Messages Deleted",
            LoggerEmbed.RED,
            description=(
                f"**Channel:** "
                f"{channel.mention if channel else f'<#{payload.channel_id}>'}\n"
                f"**Count:** {len(payload.message_ids)}"
            ),
        )
        LoggerEmbed.finalize(embed)
        await self.send(guild, MESSAGE, embed)
