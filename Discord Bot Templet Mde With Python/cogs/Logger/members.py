"""Logs member joins, leaves, and profile/role changes."""
import time

import discord
from discord.ext import commands, tasks

from .audit import resolve_moderator
from .base import BaseLogger
from .config import (MEMBER, MODERATION, EV_MEMBER_JOIN, EV_MEMBER_LEAVE,
    EV_MEMBER_KICK, EV_NICKNAME, EV_AVATAR, EV_ROLE_MEMBER)
from .embeds import LoggerEmbed, user_line
from .database import db

# Role-batch windows (see _queue_role_changes / _flush_due_role_batches).
# A user picking roles fires one member update per role; the batch
# waits until they stop picking for this long, then posts one embed
# with every role at once. MAX_WAIT is the backstop so a slow but
# steady picker is still logged within half an hour instead of the
# batch sitting forever.
ROLE_BATCH_INACTIVITY_SECONDS = 300
ROLE_BATCH_MAX_WAIT_SECONDS = 1800
# How long a looked-up intro role id is trusted before re-reading
# the Introduction config (a changed intro role is picked up at
# most this late). A failed lookup is cached only 60 s so a DB
# outage does not leave the skip stale.
INTRO_ROLE_CACHE_TTL = 600
INTRO_ROLE_FAILURE_TTL = 60
# A flush that keeps failing (not a toggle-off or a left guild) is
# retried this many times, then dropped with a log line -- a poisoned
# batch must not loop forever, and a lost log must not vanish
# silently.
ROLE_BATCH_MAX_RETRIES = 3


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _role_mentions(roles):
    """One role mention per line, capped so the field stays under
    Discord's 1024-char field cap: list as many as fit, then a
    '+N more' line instead of truncating mid-mention."""
    lines = []
    used = 0
    for role in roles:
        text = role.mention
        extra = len(text) + (1 if lines else 0)
        if lines and used + extra > 1000:
            break
        lines.append(text)
        used += extra
    if len(lines) < len(roles):
        lines.append("+%d more" % (len(roles) - len(lines)))
    return "\n".join(lines)


class MemberLogger(BaseLogger):
    def __init__(self, bot):
        super().__init__(bot)
        # Pending role batches, keyed (guild_id, user_id). Each entry
        # holds the member, the added/removed roles so far, and the
        # first/last change times the sweeper flushes on.
        self._pending_roles = {}
        # Intro role ids, keyed guild_id: (role_id_or_None, expires_at).
        self._intro_role_cache = {}
        self._flush_role_batches.start()

    def cog_unload(self):
        self._flush_role_batches.cancel()

    @commands.Cog.listener()
    async def on_member_join(self, member):
        if not db.is_enabled(member.guild.id, EV_MEMBER_JOIN):
            return
        embed = LoggerEmbed.base(
            "📥 Member Joined",
            LoggerEmbed.GREEN,
            description=(
                f"**User:** {user_line(member)}\n"
                f"**Account Created:** "
                f"{discord.utils.format_dt(member.created_at, style='R')}\n"
                f"**Member Count:** {member.guild.member_count}"
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        # Distinguish kicks from plain leaves via the audit log.
        entry = await self.audit_entry(
            member.guild, discord.AuditLogAction.kick, target_id=member.id
        )
        if entry and db.is_enabled(member.guild.id, EV_MEMBER_KICK):
            age = (discord.utils.utcnow() - entry.created_at).total_seconds()
            if age < 15:
                mod = await resolve_moderator(
                    member.guild, self.bot, discord.AuditLogAction.kick,
                    member.id, ("kick",), entry=entry,
                )
                embed = LoggerEmbed.base(
                    "👢 Member Kicked",
                    LoggerEmbed.RED,
                    description=(
                        f"**User:** {user_line(member)}\n"
                        f"**Moderator:** {mod['mention']} [{mod['name']}]\n"
                        f"**Reason:** {mod['reason'] or 'No reason provided.'}"
                    ),
                )
                LoggerEmbed.author(embed, member)
                LoggerEmbed.finalize(embed)
                await self.send(member.guild, MODERATION, embed)
                return
        if not db.is_enabled(member.guild.id, EV_MEMBER_LEAVE):
            return
        embed = LoggerEmbed.base(
            "📤 Member Left",
            LoggerEmbed.RED,
            description=(
                f"**User:** {user_line(member)}"
                + (
                    f"\n**Joined:** "
                    f"{discord.utils.format_dt(member.joined_at, style='R')}"
                    if member.joined_at else ""
                )
            ),
        )
        LoggerEmbed.author(embed, member)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        if before.nick != after.nick:
            await self._nickname_change(before, after)
        if before.display_avatar != after.display_avatar:
            await self._avatar_change(after)
        added = [r for r in after.roles if r not in before.roles]
        removed = [r for r in before.roles if r not in after.roles]
        if not added and not removed:
            return
        # The intro role is already logged by the Introduction cog
        # (Detected / Assigned / Manual embeds) -- logging it here
        # too would double-log every introduction.
        intro_role_id = await self._get_intro_role_id(after.guild)
        if intro_role_id is not None:
            added = [r for r in added if r.id != intro_role_id]
            removed = [r for r in removed if r.id != intro_role_id]
        if not added and not removed:
            return
        # Roles queue for one batched embed (see _flush_role_batches);
        # nothing is sent here.
        self._queue_role_changes(after, added, removed)

    async def _get_intro_role_id(self, guild):
        """Cached intro role id for a guild (None when not configured).

        The Introduction cog owns the config; this only reads it.
        Cached per guild so a role-heavy server does not hit the DB
        on every member update.
        """
        now = time.monotonic()
        cached = self._intro_role_cache.get(guild.id)
        if cached is not None and now < cached[1]:
            return cached[0]
        role_id = None
        ttl = INTRO_ROLE_CACHE_TTL
        try:
            from data.DB.Storage.storage import get_introduction_config
            cfg = await get_introduction_config(str(guild.id))
            role_id = _safe_int(cfg.get("role_id"))
        except Exception as e:
            print(f"[LOGGER] ERROR: intro-role lookup failed in guild "
                  f"{guild.id}: {e!r}")
            ttl = INTRO_ROLE_FAILURE_TTL
        self._intro_role_cache[guild.id] = (role_id, now + ttl)
        return role_id

    def _queue_role_changes(self, member, added, removed):
        """Merge one role diff into the member's pending batch.

        A role added and then removed again inside the window nets
        out (and vice versa), so the flushed embed only ever shows
        the roles the member actually ends up with / without.
        """
        key = (member.guild.id, member.id)
        now = time.monotonic()
        entry = self._pending_roles.get(key)
        if entry is None:
            entry = {
                "guild_id": member.guild.id,
                "user_id": member.id,
                "member": member,
                "added": [],
                "removed": [],
                "first_seen": now,
                "last_change": now,
                "retries": 0,
            }
            self._pending_roles[key] = entry
        entry["last_change"] = now
        entry["member"] = member
        for role in added:
            if any(r.id == role.id for r in entry["removed"]):
                # Added again after being removed in this window: it
                # nets out (the member ends up with the role as
                # before), so it leaves "removed" and is NOT added.
                entry["removed"] = [r for r in entry["removed"]
                                    if r.id != role.id]
            elif not any(r.id == role.id for r in entry["added"]):
                entry["added"].append(role)
        for role in removed:
            if any(r.id == role.id for r in entry["added"]):
                # Removed again after being added in this window: it
                # nets out, so it leaves "added" and is NOT removed.
                entry["added"] = [r for r in entry["added"]
                                  if r.id != role.id]
            elif not any(r.id == role.id for r in entry["removed"]):
                entry["removed"].append(role)
        if not entry["added"] and not entry["removed"]:
            del self._pending_roles[key]

    @tasks.loop(minutes=1)
    async def _flush_role_batches(self):
        """Sweep pending role batches (same guarded pattern as the
        event-history prune in LoggerCommands: one failure logs and
        the next tick retries, so a bad batch cannot kill the loop)."""
        try:
            await self._flush_due_role_batches()
        except Exception as e:
            print(f"[LOGGER] ERROR: role-batch sweep failed: {e!r}; "
                  "will retry next sweep")

    @_flush_role_batches.before_loop
    async def _before_flush_role_batches(self):
        await self.bot.wait_until_ready()

    async def _flush_due_role_batches(self, now=None):
        """Flush batches idle for ROLE_BATCH_INACTIVITY_SECONDS or
        older than ROLE_BATCH_MAX_WAIT_SECONDS. ``now`` is injectable
        so the harness can simulate time passing."""
        now = time.monotonic() if now is None else now
        due = [key for key, e in self._pending_roles.items()
               if now - e["last_change"] >= ROLE_BATCH_INACTIVITY_SECONDS
               or now - e["first_seen"] >= ROLE_BATCH_MAX_WAIT_SECONDS]
        for key in due:
            entry = self._pending_roles.pop(key, None)
            if entry is None:
                continue
            try:
                await self._flush_role_batch(entry)
            except Exception as e:
                # Bounded retry, not a silent drop and not an endless
                # loop: requeue once a minute up to MAX_RETRIES.
                entry["retries"] = entry.get("retries", 0) + 1
                if entry["retries"] >= ROLE_BATCH_MAX_RETRIES:
                    print(f"[LOGGER] ERROR: dropping role batch for user "
                          f"{entry['user_id']} after {entry['retries']} "
                          f"failed flushes: {e!r}")
                else:
                    print(f"[LOGGER] ERROR: role-batch flush failed "
                          f"(attempt {entry['retries']}): {e!r}; retrying")
                    entry["last_change"] = now
                    self._pending_roles[key] = entry

    async def _flush_role_batch(self, entry):
        """One embed for a member's whole batch, to the member log
        channel. The EV_ROLE_MEMBER toggle is checked here, at flush
        time, not when the roles were queued."""
        guild = self.bot.get_guild(entry["guild_id"])
        if guild is None:
            return
        if not db.is_enabled(guild.id, EV_ROLE_MEMBER):
            return
        member = guild.get_member(entry["user_id"]) or entry["member"]
        # Semantic color: green when only roles were added, red when
        # only removed, yellow when the batch mixed both.
        if entry["added"] and not entry["removed"]:
            color = LoggerEmbed.GREEN
        elif entry["removed"] and not entry["added"]:
            color = LoggerEmbed.RED
        else:
            color = LoggerEmbed.YELLOW
        embed = LoggerEmbed.base(
            "🎭 Roles Updated",
            color,
            description=f"**User:** {user_line(member)}",
        )
        LoggerEmbed.author(embed, member)
        added_text = _role_mentions(entry["added"])
        removed_text = _role_mentions(entry["removed"])
        if added_text:
            LoggerEmbed.field(embed, "Roles Added", added_text)
        if removed_text:
            LoggerEmbed.field(embed, "Roles Removed", removed_text)
        LoggerEmbed.finalize(embed)
        await self.send(guild, MEMBER, embed)

    async def _nickname_change(self, before, after):
        if not db.is_enabled(after.guild.id, EV_NICKNAME):
            return
        embed = LoggerEmbed.base(
            "✏ Nickname Changed",
            LoggerEmbed.BLUE,
            description=(
                f"**User:** {user_line(after)}\n"
                f"**Before:** {before.nick or '*None*'}\n"
                f"**After:** {after.nick or '*None*'}"
            ),
        )
        LoggerEmbed.author(embed, after)
        LoggerEmbed.finalize(embed)
        await self.send(after.guild, MEMBER, embed)

    async def _avatar_change(self, member):
        if not db.is_enabled(member.guild.id, EV_AVATAR):
            return
        embed = LoggerEmbed.base(
            "🖼 Avatar Changed",
            LoggerEmbed.BLUE,
            description=f"**User:** {user_line(member)}",
        )
        LoggerEmbed.author(embed, member)
        embed.set_image(url=member.display_avatar.url)
        LoggerEmbed.finalize(embed)
        await self.send(member.guild, MEMBER, embed)

