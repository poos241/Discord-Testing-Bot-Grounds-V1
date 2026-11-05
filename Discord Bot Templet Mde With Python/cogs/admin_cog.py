# cogs/admin_cog.py
import time
import re
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands, tasks
import os
import sys
import subprocess
import asyncio
import aiohttp
from config import  GUILD_IDS, admin_required, is_owner, load_json, save_json, autocomplete_commands , extra_help
import traceback

from data.DB.Storage.storage import (
    get_timeout_board_config,
    save_timeout_board_config,
    delete_timeout_board_config,
    list_timeout_board_configs,
)

USERINFO_COOLDOWN = 60


# ---------------------------------------------------------------------------
# /userinfo mini mod panel: Timeout / Kick / Ban buttons (+ test mode)
# ---------------------------------------------------------------------------

def parse_mod_duration(text):
    """Parse '10m', '2h', '1d', '30s', '1w', and combined forms like
    '1h30m' or '2w4d' (bare number = minutes) -> timedelta.

    Returns None when the text is invalid or outside Discord's 28-day cap.
    """
    clean = re.sub(r"\s+", "", text or "")
    if not clean:
        return None
    # Bare number = minutes (legacy behaviour).
    if clean.isdigit():
        return _duration_from_seconds(int(clean) * 60)
    parts = re.findall(r"(\d+)([smhdwSMHDW])", clean)
    if not parts:
        return None
    if "".join(f"{n}{u}" for n, u in parts).lower() != clean.lower():
        return None
    seconds = sum(
        int(n) * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[u.lower()]
        for n, u in parts
    )
    return _duration_from_seconds(seconds)


def _duration_from_seconds(seconds):
    """timedelta for a second count, or None when out of (0, 28d]."""
    delta = timedelta(seconds=seconds)
    if delta <= timedelta(0) or delta > timedelta(days=28):
        return None
    return delta


# Timeout presets (Little Haven: light 5m / short 15m / medium 1h /
# long 1d / extended 1w / severe 2w). Values are (timedelta, label).
TIMEOUT_PRESETS = {
    "light": (timedelta(minutes=5), "light (5m)"),
    "short": (timedelta(minutes=15), "short (15m)"),
    "medium": (timedelta(hours=1), "medium (1h)"),
    "long": (timedelta(days=1), "long (1d)"),
    "extended": (timedelta(weeks=1), "extended (1w)"),
    "severe": (timedelta(weeks=2), "severe (2w)"),
}


def _resolve_timeout_duration(preset, raw):
    """Resolve a preset and/or free-form duration into (timedelta, label).

    Returns (None, error_message) when neither is usable.
    """
    if preset:
        entry = TIMEOUT_PRESETS.get(preset)
        if entry is None:
            return None, "Unknown preset."
        return entry[0], entry[1]
    if raw:
        duration = parse_mod_duration(raw)
        if duration is None:
            return None, "Couldn't parse that duration. Try e.g. `10m`, `2h`, `1d`, or a preset."
        return duration, raw.strip()
    return None, "Give a preset or a duration (e.g. `1h30m`)."


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class TimeoutModal(discord.ui.Modal):
    def __init__(self, panel, member):
        super().__init__(title=f"Timeout {member.display_name}"[:45])
        self.panel = panel
        self.member_id = member.id
        self.add_item(discord.ui.InputText(
            label="Duration",
            placeholder="10m, 2h, 1d, 1w (max 28d)",
            max_length=12,
        ))
        self.add_item(discord.ui.InputText(
            label="Reason",
            style=discord.InputTextStyle.paragraph,
            placeholder="Why are they being timed out?",
            max_length=400,
        ))

    async def callback(self, interaction: discord.Interaction):
        raw = (self.children[0].value or "").strip()
        duration = parse_mod_duration(raw)
        reason = (self.children[1].value or "").strip() or "No reason given"
        if duration is None:
            await interaction.response.send_message(
                "\u274c Couldn't parse that duration. Try e.g. `10m`, `2h`, `1d`.",
                ephemeral=True,
            )
            return
        member = self.panel.guild.get_member(self.member_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would timeout {member.mention} for `{raw}`\n**Reason:** {reason}",
                ephemeral=True,
            )
            await self.panel._refresh_panel()
            return
        active_until = _active_timeout_until(self.panel.guild, member)
        if active_until is not None:
            summary = f"\u23f1\ufe0f Timeout {member.mention} for `{raw}`\n**Reason:** {reason}"

            async def _proceed(inter):
                await inter.response.edit_message(
                    content=f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
                    view=ModConfirmView(
                        self.panel, "timeout",
                        {"reason": reason, "duration": duration, "duration_str": raw},
                        summary,
                    ),
                )

            await interaction.response.send_message(
                f"\u23f1\ufe0f {member.mention} already has an active timeout "
                f"(until <t:{int(active_until)}:R>).\n"
                f"Replace it with `{raw}`?\n**Reason:** {reason}",
                view=TimeoutReplaceView(
                    self.panel.guild.id, member.id, summary, _proceed
                ),
                ephemeral=True,
            )
            return
        summary = f"\u23f1\ufe0f Timeout {member.mention} for `{raw}`\n**Reason:** {reason}"
        await interaction.response.send_message(
            f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
            view=ModConfirmView(
                self.panel, "timeout",
                {"reason": reason, "duration": duration, "duration_str": raw},
                summary,
            ),
            ephemeral=True,
        )


class KickModal(discord.ui.Modal):
    def __init__(self, panel, member):
        super().__init__(title=f"Kick {member.display_name}"[:45])
        self.panel = panel
        self.member_id = member.id
        self.add_item(discord.ui.InputText(
            label="Reason",
            style=discord.InputTextStyle.paragraph,
            placeholder="Why are they being kicked?",
            max_length=400,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or "No reason given"
        member = self.panel.guild.get_member(self.member_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would kick {member.mention}\n**Reason:** {reason}",
                ephemeral=True,
            )
            await self.panel._refresh_panel()
            return
        summary = f"\U0001f462 Kick {member.mention}\n**Reason:** {reason}"
        await interaction.response.send_message(
            f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
            view=ModConfirmView(self.panel, "kick", {"reason": reason}, summary),
            ephemeral=True,
        )


class BanModal(discord.ui.Modal):
    def __init__(self, panel):
        target = panel.target
        name = target.display_name if isinstance(target, discord.Member) else target.name
        super().__init__(title=f"Ban {name}"[:45])
        self.panel = panel
        self.add_item(discord.ui.InputText(
            label="Reason",
            style=discord.InputTextStyle.paragraph,
            placeholder="Why are they being banned?",
            max_length=400,
        ))
        self.add_item(discord.ui.InputText(
            label="Delete recent messages (0-7 days)",
            placeholder="0",
            max_length=1,
            required=False,
        ))
        self.add_item(discord.ui.InputText(
            label="Duration (blank = permanent)",
            placeholder="e.g. 7d, 12h, 30m",
            max_length=10,
            required=False,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or "No reason given"
        days_raw = (self.children[1].value or "0").strip()
        days = int(days_raw) if days_raw.isdigit() else -1
        if days < 0 or days > 7:
            await interaction.response.send_message(
                "\u274c Message-delete days must be 0\u20137.", ephemeral=True
            )
            return
        dur_raw = (self.children[2].value or "").strip()
        duration = None
        dur_desc = "permanent"
        if dur_raw and dur_raw.lower() not in ("permanent", "perm", "forever"):
            duration = parse_mod_duration(dur_raw)
            if duration is None:
                await interaction.response.send_message(
                    "\u274c Duration must look like `30m`, `12h`, `7d`, `1w` (max 28d), "
                    "or be left blank for a permanent ban.",
                    ephemeral=True,
                )
                return
            dur_desc = dur_raw
        mention = self.panel.target.mention
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would ban {mention} (delete {days}d of messages, {dur_desc})\n**Reason:** {reason}",
                ephemeral=True,
            )
            await self.panel._refresh_panel()
            return
        summary = (f"\U0001f528 Ban {mention} (delete {days}d of messages, {dur_desc})\n"
                   f"**Reason:** {reason}")
        await interaction.response.send_message(
            f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
            view=ModConfirmView(
                self.panel, "ban",
                {"reason": reason, "delete_days": days, "duration": duration,
                 "duration_desc": dur_desc},
                summary,
            ),
            ephemeral=True,
        )


async def _purge_user_messages(guild, target_id, channels, limit):
    """Purge target's messages across channels. Returns (total, per_channel_lines)."""
    def is_target(msg):
        return msg.author.id == target_id

    total = 0
    per_channel = []
    for ch in channels:
        try:
            deleted = await ch.purge(limit=limit, check=is_target)
        except (discord.Forbidden, discord.HTTPException):
            per_channel.append(f"\u26a0\ufe0f Skipped {ch.mention} (no access)")
            continue
        total += len(deleted)
        per_channel.append(f"{len(deleted)} in {ch.mention}")
    return total, per_channel


def _clear_channels_all(guild):
    """All text channels the bot can read/purge in."""
    return [
        ch for ch in guild.text_channels
        if ch.permissions_for(guild.me).read_message_history
        and ch.permissions_for(guild.me).manage_messages
    ]


class ClearAmountModal(discord.ui.Modal):
    """How-many form for the clear-messages action (channel already picked)."""

    def __init__(self, panel, channel):
        label = f"#{channel.name}" if channel else "all channels"
        super().__init__(title=f"Clear messages in {label}"[:45])
        self.panel = panel
        self.channel = channel
        self.add_item(discord.ui.InputText(
            label="How many messages",
            placeholder="a number or 'all'",
            value="100",
            max_length=10,
        ))

    async def callback(self, interaction: discord.Interaction):
        how_raw = (self.children[0].value or "100").strip()
        guild = self.panel.guild
        target_id = self.panel.target_id

        if self.channel is None:
            channels = _clear_channels_all(guild)
            where_desc = "all channels"
        else:
            ch = guild.get_channel(self.channel.id)
            perms = ch.permissions_for(guild.me) if ch else None
            if ch is None or not (perms.read_message_history and perms.manage_messages):
                await interaction.response.send_message(
                    "\u274c I can't manage messages there anymore.", ephemeral=True
                )
                return
            channels = [ch]
            where_desc = ch.mention

        if how_raw.lower() == "all":
            limit = None
            how_desc = "all of them"
        elif how_raw.isdigit() and int(how_raw) > 0:
            limit = int(how_raw)
            how_desc = f"up to {limit}"
        else:
            await interaction.response.send_message(
                "\u274c How many must be a positive number or 'all'.", ephemeral=True
            )
            return

        mention = self.panel.target.mention
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would clear {mention}'s messages in {where_desc} ({how_desc})",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        total, per_channel = await _purge_user_messages(guild, target_id, channels, limit)
        lines = "\n".join(per_channel[:10])
        if len(per_channel) > 10:
            lines += f"\n\u2026and {len(per_channel) - 10} more channels"
        _record_case(guild.id, target_id, "clear",
                     f"Cleared {total} messages in {where_desc} ({how_desc})",
                     interaction.user)
        await interaction.followup.send(
            f"\U0001f9f9 Cleared **{total}** messages from {mention} in {where_desc}.\n{lines}",
            ephemeral=True,
        )
        # Log the purge to the moderation log channel if the Logger is loaded.
        try:
            logger_cog = interaction.client.get_cog("ModerationLogger")
            if logger_cog is not None:
                embed = discord.Embed(
                    title="\U0001f9f9 Messages Cleared",
                    color=discord.Color.orange(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="User", value=f"{mention}\n`{target_id}`", inline=True)
                embed.add_field(name="Moderator", value=str(interaction.user), inline=True)
                embed.add_field(name="Where", value=where_desc, inline=True)
                embed.add_field(name="Deleted", value=f"**{total}** messages ({how_desc})")
                embed.set_footer(text="Kush Bush Logger")
                await logger_cog.send(guild, "moderation", embed)
        except Exception:
            pass


class ClearChannelSelect(discord.ui.Select):
    """Channel picker for the clear-messages action."""

    def __init__(self, panel):
        super().__init__(
            select_type=discord.ComponentType.channel_select,
            channel_types=[discord.ChannelType.text],
            placeholder="Pick a channel to clear messages from\u2026",
        )
        self.panel = panel

    async def callback(self, interaction: discord.Interaction):
        channel = self.values[0]
        await interaction.response.send_modal(ClearAmountModal(self.panel, channel))


class ClearPickView(discord.ui.View):
    """Pick one channel (or all) for clearing a user's messages."""

    def __init__(self, panel):
        super().__init__(timeout=300)
        self.panel = panel
        self.add_item(ClearChannelSelect(panel))

    @discord.ui.button(label="All channels", style=discord.ButtonStyle.primary)
    async def all_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(ClearAmountModal(self.panel, None))


MOD_DATA_FILE = "mod_data.json"


def _mod_record(guild_id, user_id):
    """Load mod_data.json and return (full_data, user_record)."""
    data = load_json(MOD_DATA_FILE) or {}
    grec = data.setdefault(str(guild_id), {})
    urec = grec.setdefault(str(user_id), {"warns": [], "notes": []})
    urec.setdefault("warns", [])
    urec.setdefault("notes", [])
    return data, urec


def _save_mod_data(data):
    save_json(MOD_DATA_FILE, data)


def _record_case(guild_id, user_id, action, reason, moderator, extra=None):
    """Append a moderation case to the user's history (keeps last 50)."""
    data, urec = _mod_record(guild_id, user_id)
    cases = urec.setdefault("cases", [])
    try:
        mod_id = moderator.id
    except AttributeError:
        mod_id = None
    cases.append({
        "action": action,
        "reason": reason,
        "mod_id": mod_id,
        "mod_name": str(moderator),
        "ts": time.time(),
        "extra": extra or {},
    })
    if len(cases) > 50:
        del cases[:-50]
    _save_mod_data(data)


def _tempban_data(guild_id):
    """Load mod_data.json and return (full_data, tempbans_dict)."""
    data = load_json(MOD_DATA_FILE) or {}
    grec = data.setdefault(str(guild_id), {})
    return data, grec.setdefault("tempbans", {})


def _timeout_data(guild_id):
    """Load mod_data.json and return (full_data, timeouts_dict).

    timeouts: {user_id: {"until": epoch_seconds, "reason": str,
    "mod_id": int|None, "mod_name": str}} -- Discord timeouts the bot
    applied or detected, so the board can list them after a restart.
    """
    data = load_json(MOD_DATA_FILE) or {}
    grec = data.setdefault(str(guild_id), {})
    return data, grec.setdefault("timeouts", {})


# Guild ids whose timeout board needs a refresh. _do_timeout, the panel,
# the sweep and manual detection add to this; the board loop drains it.
_BOARD_REFRESH_PENDING = set()


def _request_board_refresh(guild_id):
    """Ask the board loop to refresh one guild on its next tick."""
    try:
        _BOARD_REFRESH_PENDING.add(int(guild_id))
    except (TypeError, ValueError):
        pass


def _active_timeout_until(guild, member):
    """Epoch seconds when the member's current timeout ends, or None."""
    now = time.time()
    try:
        live = getattr(member, "timed_out_until", None)
        if live is not None and live.timestamp() > now:
            return live.timestamp()
    except Exception:
        pass
    try:
        _, timeouts = _timeout_data(guild.id)
        entry = timeouts.get(str(member.id)) or {}
        until = entry.get("until", 0) or 0
        if until > now:
            return until
    except Exception:
        pass
    return None


def _latest_timeout_case(guild_id, user_id):
    """(reason, mod_name) from the user's latest timeout case, if any."""
    try:
        data = load_json(MOD_DATA_FILE) or {}
        urec = data.get(str(guild_id), {}).get(str(user_id), {})
        for case in reversed(urec.get("cases", []) or []):
            if case.get("action") == "timeout":
                return case.get("reason") or "No reason given", case.get("mod_name") or "Unknown"
    except Exception:
        pass
    return "Timed out in Discord", "Unknown"


def _short_reason(text, limit=80):
    """One-line reason for the board (no newlines, capped)."""
    clean = " ".join(str(text or "").split())
    if len(clean) > limit:
        return clean[: limit - 3] + "..."
    return clean or "No reason given"


async def _dm_target(target, text):
    """Try to DM someone. Returns True on success, False when DMs are closed."""
    try:
        await target.send(text)
        return True
    except Exception:
        return False


async def _do_timeout(guild, member, duration, raw, reason, moderator, dm_enabled=True):
    """Apply a Discord timeout and record it. Returns a result string.

    Shared by the panel confirm flow and the /timeout command so both
    behave identically. Also stores the timeout (for the board) and asks
    the board loop to refresh.
    """
    audit = f"{moderator} ({getattr(moderator, 'id', '?')}): {reason}"

    def dm_note(ok):
        return "\U0001f4e8 DM sent" if ok else "\U0001f4ea Couldn't DM them (DMs closed?)"

    note = ""
    if dm_enabled:
        ok = await _dm_target(
            member,
            f"\u23f1\ufe0f You've been timed out in **{guild.name}** for `{raw}`\n**Reason:** {reason}\n\nTo appeal this, DM me the word `appeal`.",
        )
        note = f"\n{dm_note(ok)}"
    try:
        await member.timeout_for(duration, reason=audit)
    except discord.Forbidden:
        return "\u274c I can't time out that user \u2014 is my role above theirs?"
    except Exception as e:
        return f"\u274c Timeout failed: `{e}`"
    # Update the cached member so the refreshed card is accurate immediately.
    try:
        member.timed_out_until = datetime.now(timezone.utc) + duration
    except Exception:
        pass
    _record_case(guild.id, member.id, "timeout", reason, moderator, {"duration": raw})
    try:
        data, timeouts = _timeout_data(guild.id)
        timeouts[str(member.id)] = {
            "until": time.time() + duration.total_seconds(),
            "reason": reason,
            "mod_id": getattr(moderator, "id", None),
            "mod_name": str(moderator),
        }
        _save_mod_data(data)
    except Exception as e:
        print(f"[TIMEOUT] Could not store timeout for board: {e!r}")
    _request_board_refresh(guild.id)
    return f"\u23f1\ufe0f Timed out {member.mention} for `{raw}`\n**Reason:** {reason}{note}"


async def _find_timeout_actor(guild, member):
    """Best-effort: who changed this member's timeout, per the audit log.

    Returns (actor_or_None, reason_or_None). The most recent member_update
    entry for this member within the last 2 minutes wins. Returns
    (None, None) when the audit log can't be read.
    """
    try:
        async for entry in guild.audit_logs(limit=5, action=discord.AuditLogAction.member_update):
            target = getattr(entry, "target", None)
            if target is None or getattr(target, "id", None) != member.id:
                continue
            created = getattr(entry, "created_at", None)
            if created is not None:
                try:
                    age = (discord.utils.utcnow() - created).total_seconds()
                except Exception:
                    age = 0
                if age > 120:
                    continue
            return getattr(entry, "user", None), getattr(entry, "reason", None)
    except Exception as e:
        print(f"[TIMEOUT] Could not read audit log in guild {guild.id}: {e!r}")
    return None, None


async def _collect_board_entries(bot, guild):
    """Active timed punishments for the board, soonest expiry first.

    Sources: the stored Discord timeouts (pruned when expired, lifted
    early, or the member left with a full member cache) + a live member
    scan (heals timeouts the bot missed, e.g. applied while it was down)
    + active tempbans.
    """
    now = time.time()
    entries = []
    try:
        # Sync SQLite read off the event loop: a slow/locked database
        # used to stall the Discord heartbeat for 10-20s on this tick.
        data, timeouts = await asyncio.to_thread(_timeout_data, guild.id)
    except Exception as e:
        print(f"[TIMEOUT] Could not load timeouts for board in guild {guild.id}: {e!r}")
        data, timeouts = None, {}
    members = list(getattr(guild, "members", []) or [])
    member_count = getattr(guild, "member_count", None)
    cache_complete = bool(member_count) and len(members) >= member_count
    changed = False
    for uid, entry in list(timeouts.items()):
        until = (entry or {}).get("until", 0) or 0
        if until <= now:
            del timeouts[uid]
            changed = True
            continue
        member = guild.get_member(int(uid)) if str(uid).isdigit() else None
        if member is None:
            # Only trust "left the server" when the member cache is full;
            # otherwise keep the entry until it expires.
            if cache_complete:
                del timeouts[uid]
                changed = True
                continue
            # Cache incomplete: can't verify the live state, so show the
            # stored entry (it expires on its own, like a tempban).
            if str(uid).isdigit():
                entries.append({
                    "uid": int(uid), "kind": "timeout",
                    "reason": (entry or {}).get("reason") or "No reason given",
                    "mod_name": (entry or {}).get("mod_name") or "Unknown",
                    "until": until,
                })
            continue
        live = getattr(member, "timed_out_until", None)
        if live is None:
            # Timeout was lifted early (e.g. a manual removal the bot missed).
            del timeouts[uid]
            changed = True
            continue
        entries.append({
            "uid": int(uid), "kind": "timeout",
            "reason": (entry or {}).get("reason") or "No reason given",
            "mod_name": (entry or {}).get("mod_name") or "Unknown",
            "until": until,
        })
    # Heal: members Discord shows as timed out but with no stored entry.
    try:
        for member in members:
            live = getattr(member, "timed_out_until", None)
            if live is None:
                continue
            try:
                ts = live.timestamp()
            except Exception:
                continue
            if ts <= now:
                continue
            if any(e["uid"] == member.id and e["kind"] == "timeout" for e in entries):
                continue
            reason, mod_name = await asyncio.to_thread(
                _latest_timeout_case, guild.id, member.id
            )
            entries.append({
                "uid": member.id, "kind": "timeout",
                "reason": reason, "mod_name": mod_name, "until": ts,
            })
    except Exception as e:
        print(f"[TIMEOUT] Member scan failed for board in guild {guild.id}: {e!r}")
    if changed and data is not None:
        try:
            await asyncio.to_thread(_save_mod_data, data)
        except Exception:
            pass
    try:
        _, tb = await asyncio.to_thread(_tempban_data, guild.id)
        for uid, entry in list(tb.items()):
            until = (entry or {}).get("unban_at", 0) or 0
            if until <= now:
                continue
            entries.append({
                "uid": int(uid), "kind": "tempban",
                "reason": (entry or {}).get("reason") or "No reason given",
                "mod_name": (entry or {}).get("mod_name") or "Unknown",
                "until": until,
            })
    except Exception as e:
        print(f"[TIMEOUT] Could not load tempbans for board in guild {guild.id}: {e!r}")
    entries.sort(key=lambda e: e["until"])
    return entries


def _build_board_embed(entries, guild_name):
    """Embed for the Active Timeouts board. Pure function (no I/O)."""
    total = len(entries)
    shown = entries[:25]
    lines = []
    timeouts = [e for e in shown if e["kind"] == "timeout"]
    tempbans = [e for e in shown if e["kind"] == "tempban"]
    if timeouts:
        lines.append("**Timed out:**")
        for e in timeouts:
            lines.append(
                f"<@{e['uid']}> \u2014 {_short_reason(e.get('reason'))} "
                f"\u2014 expires <t:{int(e['until'])}:R> ({e.get('mod_name') or 'Unknown'})"
            )
    if tempbans:
        lines.append("**Tempbanned:**")
        for e in tempbans:
            lines.append(
                f"<@{e['uid']}> \u2014 {_short_reason(e.get('reason'))} "
                f"\u2014 unbanned <t:{int(e['until'])}:R> ({e.get('mod_name') or 'Unknown'})"
            )
    if total > len(shown):
        lines.append(f"_+{total - len(shown)} more_")
    desc = "\n".join(lines) if lines else "No active timeouts or tempbans."
    embed = discord.Embed(
        title="\u23f1\ufe0f Active Timeouts",
        description=desc,
        color=discord.Color.orange(),
        timestamp=discord.utils.utcnow(),
    )
    footer = f"Showing {len(shown)} of {total}"
    if guild_name:
        footer += f" \u2022 {guild_name}"
    embed.set_footer(text=footer)
    return embed


async def _refresh_board(bot, guild):
    """Post or edit the Active Timeouts board for one guild.

    Returns True on success. No-ops (False) when no board is configured.
    Re-posts when the stored message is gone; clears the config when the
    channel itself is gone.
    """
    try:
        cfg = await get_timeout_board_config(str(guild.id))
    except Exception as e:
        print(f"[TIMEOUT] Could not load board config for guild {guild.id}: {e!r}")
        return False
    channel_id = _safe_int((cfg or {}).get("channel_id"))
    if not channel_id:
        return False
    try:
        channel = guild.get_channel(channel_id)
        if channel is None:
            try:
                channel = await guild.fetch_channel(channel_id)
            except discord.NotFound:
                print(f"[TIMEOUT] Board channel {channel_id} gone in guild {guild.id}; clearing board config.")
                try:
                    await delete_timeout_board_config(str(guild.id))
                except Exception:
                    pass
                return False
            except Exception as e:
                print(f"[TIMEOUT] Could not fetch board channel {channel_id} in guild {guild.id}: {e!r}")
                return False
        if not isinstance(channel, discord.TextChannel):
            return False
        entries = await _collect_board_entries(bot, guild)
        embed = _build_board_embed(entries, getattr(guild, "name", ""))
        message_id = _safe_int((cfg or {}).get("message_id"))
        if message_id:
            try:
                msg = await channel.fetch_message(message_id)
                await msg.edit(embed=embed)
                return True
            except discord.NotFound:
                pass  # Message deleted: fall through and re-post.
            except Exception as e:
                print(f"[TIMEOUT] Could not edit board message in guild {guild.id}: {e!r}")
                return False
        msg = await channel.send(embed=embed)
        try:
            await save_timeout_board_config(str(guild.id), {
                "channel_id": str(channel_id),
                "message_id": str(msg.id),
            })
        except Exception as e:
            print(f"[TIMEOUT] Could not save board message id for guild {guild.id}: {e!r}")
        return True
    except Exception as e:
        print(f"[TIMEOUT] Board refresh failed for guild {guild.id}: {e!r}")
        return False


class TimeoutReplaceView(discord.ui.View):
    """Replace/Cancel when the target already has an active timeout.

    The pending timeout lives in this view instance (keyed by its
    guild+user); the view expires after 5 minutes.
    """

    def __init__(self, guild_id, user_id, summary, on_replace):
        super().__init__(timeout=300)
        self.guild_id = guild_id
        self.user_id = user_id
        self.summary = summary
        self.on_replace = on_replace
        self.done = False

    @discord.ui.button(label="Replace timeout", style=discord.ButtonStyle.danger)
    async def replace_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        try:
            await self.on_replace(interaction)
        except Exception as e:
            print(f"[TIMEOUT] Replace failed: {e!r}")
            try:
                await interaction.response.edit_message(content="\u274c Replace failed.", view=None)
            except Exception:
                pass

    @discord.ui.button(label="Keep current timeout", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        await interaction.response.edit_message(
            content="\u274c Kept the current timeout.", view=None
        )


class WarnModal(discord.ui.Modal):
    def __init__(self, panel):
        target = panel.target
        name = target.display_name if isinstance(target, discord.Member) else target.name
        super().__init__(title=f"Warn {name}"[:45])
        self.panel = panel
        self.add_item(discord.ui.InputText(
            label="Reason",
            style=discord.InputTextStyle.paragraph,
            placeholder="What did they do?",
            max_length=400,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or "No reason given"
        mention = self.panel.target.mention
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would warn {mention}\n**Reason:** {reason}",
                ephemeral=True,
            )
            await self.panel._refresh_panel()
            return
        summary = f"\u26a0\ufe0f Warn {mention}\n**Reason:** {reason}"
        await interaction.response.send_message(
            f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
            view=ModConfirmView(self.panel, "warn", {"reason": reason}, summary),
            ephemeral=True,
        )


class NoteAddModal(discord.ui.Modal):
    def __init__(self, notes_view):
        super().__init__(title="Add mod note")
        self.notes_view = notes_view
        self.add_item(discord.ui.InputText(
            label="Note",
            style=discord.InputTextStyle.paragraph,
            placeholder="Only mods will see this\u2026",
            max_length=500,
        ))

    async def callback(self, interaction: discord.Interaction):
        text = (self.children[0].value or "").strip()
        if not text:
            await interaction.response.send_message("\u274c Note can't be empty.", ephemeral=True)
            return
        data, urec = _mod_record(self.notes_view.guild_id, self.notes_view.target_id)
        urec["notes"].append({
            "text": text,
            "mod_id": interaction.user.id,
            "mod_name": str(interaction.user),
            "ts": time.time(),
        })
        _save_mod_data(data)
        await self.notes_view.refresh()
        await interaction.response.send_message("\U0001f4dd Note added.", ephemeral=True)
        if self.notes_view.panel is not None:
            await self.notes_view.panel._refresh_panel()


class NoteRemoveModal(discord.ui.Modal):
    def __init__(self, notes_view, count):
        super().__init__(title="Remove mod note")
        self.notes_view = notes_view
        self.add_item(discord.ui.InputText(
            label=f"Note number to remove (1-{count})",
            placeholder="e.g. 2",
            max_length=4,
        ))

    async def callback(self, interaction: discord.Interaction):
        raw = (self.children[0].value or "").strip()
        data, urec = _mod_record(self.notes_view.guild_id, self.notes_view.target_id)
        notes = urec["notes"]
        if not raw.isdigit() or not (1 <= int(raw) <= len(notes)):
            await interaction.response.send_message(
                f"\u274c Pick a number between 1 and {len(notes)}.", ephemeral=True
            )
            return
        removed = notes.pop(int(raw) - 1)
        _save_mod_data(data)
        await self.notes_view.refresh()
        await interaction.response.send_message(
            f"\U0001f5d1\ufe0f Removed note: \"{removed['text'][:80]}\"",
            ephemeral=True,
        )
        if self.notes_view.panel is not None:
            await self.notes_view.panel._refresh_panel()


class NotesView(discord.ui.View):
    """View a user's mod notes; add or remove them."""

    def __init__(self, guild, target, panel=None):
        super().__init__(timeout=300)
        self.guild_id = guild.id
        self.target_id = target.id
        self.target_mention = target.mention
        self.message = None
        self.panel = panel

    def _notes(self):
        data = load_json(MOD_DATA_FILE) or {}
        return data.get(str(self.guild_id), {}).get(str(self.target_id), {}).get("notes", [])

    def content(self):
        notes = self._notes()
        if not notes:
            body = "_No notes yet._"
        else:
            lines = []
            for i, n in enumerate(notes, 1):
                ts = datetime.fromtimestamp(n.get("ts", 0), tz=timezone.utc).strftime("%Y-%m-%d")
                lines.append(f"**{i}.** {n.get('text', '')}\n\u2014 {n.get('mod_name', '?')} \u2022 {ts}")
            body = "\n".join(lines)
        return f"\U0001f4dd Notes for {self.target_mention}:\n{body}"

    async def refresh(self):
        if self.message is None:
            return
        try:
            await self.message.edit(content=self.content(), view=self)
        except Exception:
            pass

    @discord.ui.button(label="Add note", emoji="\u2795", style=discord.ButtonStyle.primary)
    async def add_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_modal(NoteAddModal(self))

    @discord.ui.button(label="Remove note", emoji="\U0001f5d1\ufe0f", style=discord.ButtonStyle.danger)
    async def remove_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        notes = self._notes()
        if not notes:
            await interaction.response.send_message("\u274c There are no notes to remove.", ephemeral=True)
            return
        await interaction.response.send_modal(NoteRemoveModal(self, len(notes)))


class WatchAddModal(discord.ui.Modal):
    """Optional reason when adding someone to the watch list from the panel."""

    def __init__(self, panel):
        target = panel.target
        name = target.display_name if isinstance(target, discord.Member) else target.name
        super().__init__(title=f"Watch {name}"[:45])
        self.panel = panel
        self.add_item(discord.ui.InputText(
            label="Reason (optional)",
            style=discord.InputTextStyle.paragraph,
            placeholder="Why are they being watched?",
            max_length=300,
            required=False,
        ))

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or None
        panel = self.panel
        cog = panel.watch_cog
        if cog is None:
            await interaction.response.send_message(
                "\u274c The Watch List system isn't loaded.", ephemeral=True
            )
            return
        if panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would add {panel.target.mention} to the watch list",
                ephemeral=True,
            )
            await panel._refresh_panel()
            return
        target = panel.target
        display = target.display_name if isinstance(target, discord.Member) else target.name
        record = {
            "user_id": str(target.id),
            "username": target.name,
            "display_name": display,
            "added_by": str(interaction.user.id),
            "added_by_name": str(interaction.user),
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        if reason:
            record["reason"] = reason
        guild_data = cog._guild_data(panel.guild.id)
        guild_data["users"][str(target.id)] = record
        cog._save_db()
        await interaction.response.send_message(
            f"\U0001f441\ufe0f Added {target.mention} to the watch list"
            + (f"\n**Reason:** {reason}" if reason else ""),
            ephemeral=True,
        )
        await panel._refresh_panel()


class XPModal(discord.ui.Modal):
    """Add or remove XP for a manual correction."""

    def __init__(self, panel, adding):
        self.panel = panel
        self.adding = adding
        super().__init__(title=f"{'Add' if adding else 'Remove'} XP")
        self.add_item(discord.ui.InputText(
            label="Amount of XP",
            placeholder="e.g. 100",
            max_length=7,
        ))

    async def callback(self, interaction: discord.Interaction):
        raw = (self.children[0].value or "").strip()
        if not raw.isdigit() or int(raw) <= 0:
            await interaction.response.send_message(
                "\u274c Amount must be a positive whole number.", ephemeral=True
            )
            return
        amount = int(raw)
        panel = self.panel
        guild = panel.guild
        target = panel.target
        gid, uid = str(guild.id), str(target.id)
        display = target.display_name if isinstance(target, discord.Member) else target.name
        if panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would {'add' if self.adding else 'remove'} {amount} XP "
                f"{'to' if self.adding else 'from'} {target.mention}",
                ephemeral=True,
            )
            await panel._refresh_panel()
            return
        try:
            from data.DB.Storage.storage import get_levels, save_levels
            if self.adding:
                from cogs.Level_system import award_xp, levels_enabled
                if not await levels_enabled(guild.id):
                    await interaction.response.send_message(
                        "The level system is off in this server. "
                        "Turn it on with /toggle_levels first.",
                        ephemeral=True,
                    )
                    await panel._refresh_panel()
                    return
                gained = await award_xp(guild, target.id, display, amount, apply_event=False)
                db = await get_levels(gid)
                ud = db.get(uid, {})
                lvl, xp = ud.get("level", 1), ud.get("xp", 0)
                extra = f"\n\U0001f389 Leveled up to **{lvl}**!" if gained else ""
                await interaction.response.send_message(
                    f"\u2795 Added **{amount}** XP to {target.mention} "
                    f"(now Level **{lvl}**, **{xp}** XP){extra}",
                    ephemeral=True,
                )
                await panel._refresh_panel()
            else:
                db = await get_levels(gid)
                ud = db.get(uid)
                if not ud:
                    await interaction.response.send_message(
                        "\u274c That user has no XP recorded.", ephemeral=True
                    )
                    return
                ud["xp"] = ud.get("xp", 0) - amount
                while ud["xp"] < 0 and ud.get("level", 1) > 1:
                    ud["level"] -= 1
                    ud["xp"] += ud["level"] * 100
                ud["xp"] = max(0, ud["xp"])
                await save_levels(gid, db)
                await interaction.response.send_message(
                    f"\u2796 Removed **{amount}** XP from {target.mention} "
                    f"(now Level **{ud['level']}**, **{ud['xp']}** XP)",
                    ephemeral=True,
                )
                await panel._refresh_panel()
        except Exception as e:
            await interaction.response.send_message(f"\u274c XP update failed: `{e}`", ephemeral=True)


async def build_userinfo_embed(guild, target, is_member, test_mode, watch_cog, requester_name):
    """Build the /userinfo card embed from live data.

    Returns (embed, state) where state has is_member/is_banned/is_timed_out/is_watched.
    """
    guild_id = guild.id
    # ---- Ban status ----
    ban_status = "No"
    ban_reason = None
    is_banned = False
    try:
        ban = await guild.fetch_ban(target)
        ban_status = "\U0001f528 Yes"
        ban_reason = ban.reason
        is_banned = True
    except discord.NotFound:
        pass
    except discord.Forbidden:
        ban_status = "Unknown (missing Ban Members permission)"

    # ---- Server XP ----
    xp_line = "No XP recorded yet"
    try:
        from data.DB.Storage.storage import get_levels
        db = await get_levels(str(guild_id))
        udata = db.get(str(target.id))
        if udata:
            lvl = udata.get("level", 1)
            xp = udata.get("xp", 0)
            need = lvl * 100 - xp
            xp_line = f"Level **{lvl}** • **{xp}** XP\n{need} XP to level {lvl + 1}"
    except Exception:
        xp_line = "Couldn't load XP data"

    # ---- Watch-list status (via the cog so we share its in-memory db) ----
    watched = False
    watch_record = None
    try:
        if watch_cog is not None:
            watch_record = watch_cog._guild_data(guild_id)["users"].get(str(target.id))
        else:
            wl_data = load_json("watchlist_data.json") or {}
            watch_record = wl_data.get(str(guild_id), {}).get("users", {}).get(str(target.id))
        watched = watch_record is not None
    except Exception:
        pass

    # ---- Warns / notes ----
    warns = []
    notes = []
    try:
        md = load_json(MOD_DATA_FILE) or {}
        urec = md.get(str(guild_id), {}).get(str(target.id), {})
        warns = urec.get("warns", [])
        notes = urec.get("notes", [])
    except Exception:
        pass

    # ---- Timeout state ----
    is_timed_out = False
    if is_member:
        tu = getattr(target, "timed_out_until", None)
        if tu and tu > datetime.now(timezone.utc):
            is_timed_out = True

    # ---- Build the embed ----
    display = target.display_name if is_member else target.name
    color = (target.color if is_member and target.color != discord.Color.default()
             else discord.Color.blurple())
    info_embed = discord.Embed(
        title=f"\U0001f464 {display}",
        description=f"{target.mention}\n`{target.id}`",
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    info_embed.set_thumbnail(url=target.display_avatar.url)

    created_ts = int(target.created_at.timestamp())
    info_embed.add_field(
        name="Account",
        value=f"**Username:** `{target.name}`\n**Created:** <t:{created_ts}:F>",
        inline=True,
    )

    if is_member:
        joined = (f"<t:{int(target.joined_at.timestamp())}:F>"
                  if target.joined_at else "Unknown")
        info_embed.add_field(
            name="Server",
            value=(f"**Nickname:** `{target.display_name}`\n"
                   f"**Joined:** {joined}\n"
                   f"**Top role:** {target.top_role.mention}"),
            inline=True,
        )
        roles = [r.mention for r in target.roles if r.name != "@everyone"]
        roles_value = ", ".join(roles) if roles else "None"
        if len(roles_value) > 1024:
            roles_value = roles_value[:1000] + "…"
        info_embed.add_field(
            name=f"Roles ({len(roles)})",
            value=roles_value,
            inline=False,
        )
        status = str(target.status).title() if getattr(target, "status", None) else "Unknown"
        info_embed.add_field(
            name="Presence",
            value=f"**Status:** {status}\n**Bot:** {'Yes' if target.bot else 'No'}",
            inline=True,
        )
    else:
        info_embed.add_field(name="Server", value="*Not in this server*", inline=True)

    info_embed.add_field(name="⭐ Server XP", value=xp_line, inline=True)

    mod_value = f"**Banned:** {ban_status}"
    if ban_reason:
        mod_value += f"\n**Reason:** {ban_reason}"
    if watched and watch_record:
        adder = watch_record.get("added_by_name", "?")
        when = watch_record.get("added_at", "")
        try:
            when = f"<t:{int(datetime.fromisoformat(when).timestamp())}:D>"
        except Exception:
            when = when[:10]
        mod_value += f"\n**Watch list:** \U0001f441\ufe0f Yes (by {adder}, {when})"
        if watch_record.get("reason"):
            mod_value += f"\n**Watch reason:** \"{watch_record['reason'][:80]}\""
    else:
        mod_value += "\n**Watch list:** No"
    if warns:
        latest = warns[-1].get("reason", "")[:50]
        mod_value += f"\n**Warnings:** {len(warns)} (latest: \"{latest}\")"
    else:
        mod_value += "\n**Warnings:** 0"
    if notes:
        mod_value += f"\n**Notes:** {len(notes)}"
    info_embed.add_field(name="🛡️ Moderation", value=mod_value, inline=False)

    footer = f"Requested by {requester_name}"
    if test_mode:
        footer += " \u2022 \U0001f9ea TEST MODE \u2014 actions are simulated"
    info_embed.set_footer(text=footer)
    state = {
        "is_member": is_member,
        "is_banned": is_banned,
        "is_timed_out": is_timed_out,
        "is_watched": watched,
    }
    return info_embed, state


class ModConfirmView(discord.ui.View):
    """Confirm a warn/timeout/kick/ban, with a toggle for whether to DM the target."""

    def __init__(self, panel, action, params, summary):
        super().__init__(timeout=180)
        self.panel = panel
        self.action = action
        self.params = params
        self.summary = summary
        self.dm_enabled = True
        self.done = False

    @discord.ui.button(label="DM them: Yes", style=discord.ButtonStyle.success, row=0)
    async def dm_toggle(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.dm_enabled = not self.dm_enabled
        button.label = f"DM them: {'Yes' if self.dm_enabled else 'No'}"
        button.style = (discord.ButtonStyle.success if self.dm_enabled
                        else discord.ButtonStyle.secondary)
        await interaction.response.edit_message(view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger, row=1)
    async def confirm_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        if not await self.panel._check_action(interaction, self.action):
            return
        await interaction.response.defer(ephemeral=True)
        try:
            result = await self.panel._apply_mod_action(
                self.action, self.params, self.dm_enabled, interaction.user
            )
            # After a kick the member cache may lag behind; force the card
            # to treat them as gone.
            force = None
            if self.action == "kick" and not result.startswith("\u274c"):
                force = {"is_member": False}
            await self.panel._refresh_panel(force=force)
        except Exception as e:
            result = f"\u274c Failed: `{e}`"
        if self.action in ("ban", "kick") and not result.startswith("\u274c"):
            self.panel.last_gh_action = self.action.title()
            self.panel.last_gh_reason = self.params.get("reason", "")
        await interaction.edit_original_response(content=result, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        await interaction.response.edit_message(content="\u274c Cancelled.", view=None)


class RenameModal(discord.ui.Modal):
    """Set (or reset) a member's server nickname."""

    def __init__(self, panel):
        name = panel.target.display_name if isinstance(panel.target, discord.Member) else ""
        super().__init__(title="Rename user"[:45])
        self.panel = panel
        self.add_item(discord.ui.InputText(
            label="New nickname (blank = reset)",
            placeholder=name,
            max_length=32,
            required=False,
        ))

    async def callback(self, interaction: discord.Interaction):
        panel = self.panel
        nick = (self.children[0].value or "").strip()
        member = panel.guild.get_member(panel.target_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        if panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would rename {member.mention} to "
                f"`{nick or '(reset)'}`",
                ephemeral=True,
            )
            await panel._refresh_panel()
            return
        try:
            await member.edit(
                nick=nick or None,
                reason=f"{interaction.user} ({interaction.user.id}): renamed via panel",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "\u274c I can't rename them \u2014 is my role above theirs?", ephemeral=True
            )
            return
        except Exception as e:
            await interaction.response.send_message(f"\u274c Rename failed: `{e}`", ephemeral=True)
            return
        _record_case(panel.guild.id, panel.target_id,
                     "rename", f"Nickname set to `{nick}`" if nick else "Nickname reset",
                     interaction.user)
        await interaction.response.send_message(
            f"\u270f\ufe0f Renamed {member.mention} to `{nick}`" if nick
            else f"\u270f\ufe0f Reset {member.mention}'s nickname",
            ephemeral=True,
        )
        await panel._refresh_panel()


class StripRolesConfirmView(discord.ui.View):
    """Confirm stripping all of a member's roles."""

    def __init__(self, panel):
        super().__init__(timeout=300)
        self.panel = panel

    @discord.ui.button(label="Yes, strip all roles", style=discord.ButtonStyle.danger)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        panel = self.panel
        if not await panel._check_admin(interaction):
            return
        member = panel.guild.get_member(panel.target_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        if panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would strip all roles from {member.mention}",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        roles = [r for r in member.roles if not r.is_default()]
        try:
            await member.edit(
                roles=[],
                reason=f"{interaction.user} ({interaction.user.id}): roles stripped via panel",
            )
        except discord.Forbidden:
            await interaction.followup.send(
                "\u274c I can't edit their roles \u2014 is my role above theirs?",
                ephemeral=True,
            )
            return
        except Exception as e:
            await interaction.followup.send(f"\u274c Failed: `{e}`", ephemeral=True)
            return
        names = ", ".join(r.name for r in roles) if roles else "none"
        _record_case(panel.guild.id, panel.target_id, "strip_roles",
                     f"Removed {len(roles)} role(s): {names}", interaction.user)
        await interaction.followup.send(
            f"\U0001f9f9 Stripped **{len(roles)}** roles from {member.mention}.",
            ephemeral=True,
        )
        await panel._refresh_panel()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_message("Cancelled.", ephemeral=True)
        self.stop()


class WipeConfirmView(discord.ui.View):
    """Confirm wiping ALL of a user's server data (XP, warns, notes, watch)."""

    def __init__(self, panel):
        super().__init__(timeout=300)
        self.panel = panel

    @discord.ui.button(label="Yes, wipe everything", style=discord.ButtonStyle.danger)
    async def confirm(self, button: discord.ui.Button, interaction: discord.Interaction):
        panel = self.panel
        if not await panel._check_admin(interaction):
            return
        await interaction.response.defer(ephemeral=True)
        guild = panel.guild
        target_id = panel.target_id
        gid, uid = str(guild.id), str(target_id)
        wiped = []

        if panel.test_mode:
            await interaction.followup.send(
                f"\U0001f9ea TEST \u2014 would wipe all data for {panel.target.mention}",
                ephemeral=True,
            )
            return

        # XP / level
        try:
            from data.DB.Storage.storage import get_levels, save_levels
            db = await get_levels(gid)
            if uid in db:
                db[uid] = {"xp": 0, "level": 1,
                           "username": getattr(panel.target, "display_name", str(panel.target))}
                await save_levels(gid, db)
                wiped.append("XP/level reset")
        except Exception:
            pass

        # Warns + notes
        try:
            data, urec = _mod_record(guild.id, target_id)
            if urec.get("warns"):
                wiped.append(f"{len(urec['warns'])} warn(s)")
            if urec.get("notes"):
                wiped.append(f"{len(urec['notes'])} note(s)")
            urec["warns"] = []
            urec["notes"] = []
            _save_mod_data(data)
        except Exception:
            pass

        # Watch list
        try:
            cog = panel.watch_cog
            if cog is not None:
                guild_data = cog._guild_data(guild.id)
                if str(target_id) in guild_data["users"]:
                    guild_data["users"].pop(str(target_id), None)
                    cog._save_db()
                    wiped.append("watch entry")
        except Exception:
            pass

        detail = ", ".join(wiped) if wiped else "nothing to wipe"
        _record_case(guild.id, target_id, "wipe", f"Wiped: {detail}", interaction.user)
        await interaction.followup.send(
            f"\U0001f9f9 Wiped all data for {panel.target.mention}: {detail}.",
            ephemeral=True,
        )
        # Log to moderation log
        try:
            logger_cog = interaction.client.get_cog("ModerationLogger")
            if logger_cog is not None:
                embed = discord.Embed(
                    title="\U0001f9f9 User Data Wiped",
                    color=discord.Color.red(),
                    timestamp=discord.utils.utcnow(),
                )
                embed.add_field(name="User", value=f"{panel.target.mention}\n`{target_id}`", inline=True)
                embed.add_field(name="Moderator", value=str(interaction.user), inline=True)
                embed.add_field(name="Wiped", value=detail)
                embed.set_footer(text="Kush Bush Logger")
                await logger_cog.send(guild, "moderation", embed)
        except Exception:
            pass
        await panel._refresh_panel()
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, button: discord.ui.Button, interaction: discord.Interaction):
        await interaction.response.send_message("Wipe cancelled.", ephemeral=True)
        self.stop()


class UserinfoModView(discord.ui.View):
    """Mini admin panel attached to the /userinfo card."""

    def __init__(self, guild, target, is_member, test_mode=False, is_banned=False,
                 is_timed_out=False, watch_cog=None, is_watched=False,
                 requester_name="", viewer=None):
        super().__init__(timeout=1800)
        self.guild = guild
        self.target = target
        self.target_id = target.id
        self.test_mode = test_mode
        self.is_banned = is_banned
        self.is_timed_out = is_timed_out
        self.watch_cog = watch_cog
        self.is_watched = is_watched
        self.requester_name = requester_name
        self.viewer = viewer
        # Buttons the viewer may not use (by permission). Stored by
        # attribute name; _sync_buttons ORs these in with the
        # state-based disabling so a refresh never re-enables them.
        self._perm_disabled: set[str] = set()
        self.last_gh_action = None
        self.last_gh_reason = None
        self.message = None
        self._sync_buttons({
            "is_member": is_member,
            "is_banned": is_banned,
            "is_timed_out": is_timed_out,
            "is_watched": is_watched,
        })

    async def _apply_viewer_permissions(self, member):
        """Gray out every panel button the viewing member may not use.
        Grantable actions (warn/timeout/kick/ban/clear/banlog) use the
        custom permission check; the rest need Manage Server or
        Administrator. Buttons the viewer lacks stay disabled through
        refreshes (see _sync_buttons)."""
        from utils.permissions import (
            has_command_permission,
            _default_manage_or_admin,
        )

        self.viewer = member
        perms = getattr(member, "guild_permissions", None)
        is_admin = bool(perms and (perms.manage_guild or perms.administrator))
        # (button attribute, grantable action or None for admin-only)
        mapping = [
            ("warn_button", "warn"),
            ("timeout_button", "timeout"),
            ("kick_button", "kick"),
            ("ban_button", "ban"),
            ("clear_button", "clear_user"),
            ("ghlog_button", "banlog"),
            ("notes_button", None),
            ("watch_button", None),
            ("add_xp_button", None),
            ("remove_xp_button", None),
            ("wipe_button", None),
            ("history_button", None),
            ("rename_button", None),
            ("strip_button", None),
        ]
        self._perm_disabled = set()
        for attr, action in mapping:
            if action is not None:
                allowed = await has_command_permission(
                    self.guild, member, action, _default_manage_or_admin
                )
            else:
                allowed = is_admin
            if not allowed:
                self._perm_disabled.add(attr)
        self._sync_buttons({
            "is_member": self.guild.get_member(self.target_id) is not None,
            "is_banned": self.is_banned,
            "is_timed_out": self.is_timed_out,
            "is_watched": self.is_watched,
        })

    def _sync_buttons(self, state):
        """Match every button to the current moderation state."""
        is_member = state["is_member"]
        self.is_banned = state["is_banned"]
        self.is_timed_out = state["is_timed_out"]
        self.is_watched = state["is_watched"]
        # Timeout/kick only make sense for someone in the server.
        self.timeout_button.disabled = not is_member
        self.kick_button.disabled = not is_member
        if state["is_banned"]:
            self.ban_button.label = "Unban"
            self.ban_button.emoji = "\U0001f513"
            self.ban_button.style = discord.ButtonStyle.success
        else:
            self.ban_button.label = "Ban"
            self.ban_button.emoji = "\U0001f528"
            self.ban_button.style = discord.ButtonStyle.danger
        if state["is_timed_out"] and is_member:
            self.timeout_button.label = "Remove timeout"
            self.timeout_button.style = discord.ButtonStyle.success
        else:
            self.timeout_button.label = "Timeout"
            self.timeout_button.style = discord.ButtonStyle.primary
        if self.watch_cog is None:
            self.watch_button.disabled = True
        else:
            self.watch_button.disabled = False
            if state["is_watched"]:
                self.watch_button.label = "Unwatch"
                self.watch_button.emoji = "\U0001f441\ufe0f"
                self.watch_button.style = discord.ButtonStyle.success
            else:
                self.watch_button.label = "Watch"
                self.watch_button.emoji = "\u2795"
                self.watch_button.style = discord.ButtonStyle.secondary
        # Permission gating: a button the viewer may not use stays
        # grayed out even when the moderation state would enable it.
        for attr in (
            "warn_button", "timeout_button", "kick_button", "ban_button",
            "clear_button", "notes_button", "watch_button",
            "add_xp_button", "remove_xp_button", "ghlog_button",
            "wipe_button", "history_button", "rename_button",
            "strip_button",
        ):
            if attr in self._perm_disabled:
                getattr(self, attr).disabled = True

    async def _refresh_panel(self, force=None):
        """Rebuild the card embed and button states from live data."""
        member = self.guild.get_member(self.target_id)
        is_member = member is not None
        if force and "is_member" in force:
            # e.g. right after a kick, before the member cache catches up
            is_member = force["is_member"]
        target = member if member is not None else self.target
        self.target = target
        embed, state = await build_userinfo_embed(
            self.guild, target, is_member, self.test_mode,
            self.watch_cog, self.requester_name,
        )
        if force:
            state.update(force)
        self._sync_buttons(state)
        if self.message is not None:
            try:
                await self.message.edit(embed=embed, view=self)
            except discord.NotFound:
                # The panel message is gone (deleted, or the ephemeral
                # interaction token expired after 15 min). Stop trying;
                # buttons keep working through their own interactions.
                self.message = None
            except Exception:
                pass

    async def _apply_mod_action(self, action, params, dm_enabled, moderator):
        """Apply a warn/timeout/kick/ban. Returns a human-readable result string."""
        guild = self.guild
        target = self.target
        reason = params["reason"]
        audit = f"{moderator} ({moderator.id}): {reason}"

        def dm_note(ok):
            return "\U0001f4e8 DM sent" if ok else "\U0001f4ea Couldn't DM them (DMs closed?)"

        if action == "warn":
            note = ""
            if dm_enabled:
                ok = await _dm_target(
                    target,
                    f"\u26a0\ufe0f You've been warned in **{guild.name}**\n**Reason:** {reason}",
                )
                note = f"\n{dm_note(ok)}"
            data, urec = _mod_record(guild.id, target.id)
            urec["warns"].append({
                "reason": reason,
                "mod_id": moderator.id,
                "mod_name": str(moderator),
                "ts": time.time(),
            })
            _save_mod_data(data)
            _record_case(guild.id, target.id, "warn", reason, moderator)
            n = len(urec["warns"])
            return f"\u26a0\ufe0f Warned {target.mention} (warn #{n})\n**Reason:** {reason}{note}"

        member = guild.get_member(self.target_id)
        if member is None:
            return "\u274c That user isn't in the server anymore."

        if action == "timeout":
            return await _do_timeout(
                guild, member, params["duration"], params["duration_str"],
                reason, moderator, dm_enabled,
            )

        if action == "kick":
            try:
                await member.kick(reason=audit)
            except discord.Forbidden:
                return "\u274c I can't kick that user \u2014 is my role above theirs?"
            except Exception as e:
                return f"\u274c Kick failed: `{e}`"
            # Only DM after the kick actually went through, so a failed
            # kick never tells the user they were kicked.
            note = ""
            if dm_enabled:
                ok = await _dm_target(
                    member,
                    f"\U0001f462 You've been kicked from **{guild.name}**\n**Reason:** {reason}",
                )
                note = f"\n{dm_note(ok)}"
            _record_case(guild.id, member.id, "kick", reason, moderator)
            return f"\U0001f462 Kicked {member.mention}\n**Reason:** {reason}{note}"

        if action == "ban":
            days = params["delete_days"]
            duration = params.get("duration")
            dur_desc = params.get("duration_desc", "permanent")
            # pycord 2.x renamed Guild.ban()'s delete_message_days to
            # delete_message_seconds (0-604800). days is 0-7 here.
            delete_seconds = max(0, min(int(days or 0) * 86400, 604800))
            try:
                await guild.ban(
                    target, reason=audit, delete_message_seconds=delete_seconds
                )
            except discord.Forbidden:
                return "\u274c I can't ban that user \u2014 is my role above theirs?"
            except Exception as e:
                return f"\u274c Ban failed: `{e}`"
            # Only DM after the ban actually went through, so a failed
            # ban never tells the user they were banned.
            note = ""
            if dm_enabled:
                dur_text = f" for {dur_desc}" if duration else " permanently"
                ok = await _dm_target(
                    target,
                    f"\U0001f528 You've been banned from **{guild.name}**{dur_text}\n**Reason:** {reason}\n\nTo appeal this, DM me the word `appeal`.",
                )
                note = f"\n{dm_note(ok)}"
            label = f"tempban ({dur_desc})" if duration else "ban"
            if duration:
                tb_data, tb = _tempban_data(guild.id)
                tb[str(target.id)] = {
                    # duration is a timedelta (from parse_mod_duration);
                    # unban_at is epoch seconds, like the timeout path.
                    "unban_at": time.time() + duration.total_seconds(),
                    "reason": reason,
                    "mod_id": moderator.id,
                    "mod_name": str(moderator),
                }
                _save_mod_data(tb_data)
            _record_case(guild.id, target.id, label, reason, moderator,
                         {"duration": dur_desc} if duration else None)
            return f"\U0001f528 Banned {target.mention} ({dur_desc})\n**Reason:** {reason}{note}"

        return "\u274c Unknown action."

    async def _check_admin(self, interaction: discord.Interaction):
        perms = interaction.user.guild_permissions
        if perms.manage_guild or perms.administrator:
            return True
        await interaction.response.send_message(
            "\u274c You need **Manage Server** or **Administrator** to use this panel.",
            ephemeral=True,
        )
        return False

    async def _check_action(self, interaction: discord.Interaction, action: str):
        """Gate one moderation action (ban/kick/timeout/warn/clear_user/
        banlog) on the custom per-command permissions. Server admins
        always pass; a custom rule for the action replaces the
        Manage Server / Administrator default; with no custom rules
        the default applies. See utils/permissions.py."""
        from utils.permissions import (
            check_interaction_permission,
            _default_manage_or_admin,
        )

        return await check_interaction_permission(
            interaction, action, _default_manage_or_admin
        )

    @discord.ui.button(label="Warn", emoji="\u26a0\ufe0f", style=discord.ButtonStyle.secondary, row=0)
    async def warn_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "warn"):
            return
        await interaction.response.send_modal(WarnModal(self))

    @discord.ui.button(label="Timeout", emoji="\u23f1\ufe0f", style=discord.ButtonStyle.primary, row=0)
    async def timeout_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "timeout"):
            return
        member = self.guild.get_member(self.target_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        if self.is_timed_out:
            if self.test_mode:
                await interaction.response.send_message(
                    f"\U0001f9ea TEST \u2014 would remove timeout from {member.mention}",
                    ephemeral=True,
                )
                await self._refresh_panel()
                return
            await interaction.response.defer(ephemeral=True)
            try:
                await member.remove_timeout(
                    reason=f"{interaction.user} ({interaction.user.id}): timeout removed via panel"
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "\u274c I can't do that \u2014 is my role above theirs?", ephemeral=True
                )
                return
            except Exception as e:
                await interaction.followup.send(f"\u274c Failed: `{e}`", ephemeral=True)
                return
            try:
                member.timed_out_until = None
            except Exception:
                pass
            _record_case(self.guild.id, self.target_id, "untimeout",
                         "Timeout removed via panel", interaction.user)
            try:
                _tb_data, _timeouts = _timeout_data(self.guild.id)
                if str(self.target_id) in _timeouts:
                    del _timeouts[str(self.target_id)]
                    _save_mod_data(_tb_data)
            except Exception as e:
                print(f"[TIMEOUT] Could not clear stored timeout for {self.target_id}: {e!r}")
            _request_board_refresh(self.guild.id)
            await self._refresh_panel()
            await interaction.followup.send(
                f"\u23f1\ufe0f Removed timeout from {member.mention}", ephemeral=True
            )
            return
        await interaction.response.send_modal(TimeoutModal(self, member))

    @discord.ui.button(label="Kick", emoji="\U0001f462", style=discord.ButtonStyle.danger, row=0)
    async def kick_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "kick"):
            return
        member = self.guild.get_member(self.target_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        await interaction.response.send_modal(KickModal(self, member))

    @discord.ui.button(label="Ban", emoji="\U0001f528", style=discord.ButtonStyle.danger, row=0)
    async def ban_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "ban"):
            return
        if self.is_banned:
            if self.test_mode:
                await interaction.response.send_message(
                    f"\U0001f9ea TEST \u2014 would unban {self.target.mention}",
                    ephemeral=True,
                )
                await self._refresh_panel()
                return
            await interaction.response.defer(ephemeral=True)
            try:
                await self.guild.unban(
                    discord.Object(id=self.target_id),
                    reason=f"{interaction.user} ({interaction.user.id}): unbanned via panel",
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "\u274c I can't unban them \u2014 check my permissions.", ephemeral=True
                )
                return
            except Exception as e:
                await interaction.followup.send(f"\u274c Unban failed: `{e}`", ephemeral=True)
                return
            try:
                tb_data, tb = _tempban_data(self.guild.id)
                tb.pop(str(self.target_id), None)
                _save_mod_data(tb_data)
            except Exception:
                pass
            _record_case(self.guild.id, self.target_id, "unban",
                         "Unbanned via panel", interaction.user)
            await self._refresh_panel()
            await interaction.followup.send(
                f"\U0001f513 Unbanned {self.target.mention}", ephemeral=True
            )
            return
        await interaction.response.send_modal(BanModal(self))

    @discord.ui.button(label="Clear", emoji="\U0001f9f9", style=discord.ButtonStyle.secondary, row=0)
    async def clear_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "clear_user"):
            return
        await interaction.response.send_message(
            f"Clear {self.target.mention}'s messages \u2014 pick a channel:",
            view=ClearPickView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="Notes", emoji="\U0001f4dd", style=discord.ButtonStyle.secondary, row=1)
    async def notes_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        view = NotesView(self.guild, self.target, panel=self)
        await interaction.response.send_message(
            view.content(), view=view, ephemeral=True
        )
        try:
            view.message = await interaction.original_response()
        except Exception:
            pass

    @discord.ui.button(label="Watch", emoji="\u2795", style=discord.ButtonStyle.secondary, row=1)
    async def watch_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        cog = self.watch_cog
        if cog is None:
            await interaction.response.send_message(
                "\u274c The Watch List system isn't loaded.", ephemeral=True
            )
            return
        guild_data = cog._guild_data(self.guild.id)
        currently = str(self.target_id) in guild_data["users"]
        if currently:
            if self.test_mode:
                await interaction.response.send_message(
                    f"\U0001f9ea TEST \u2014 would remove {self.target.mention} from the watch list",
                    ephemeral=True,
                )
                await self._refresh_panel()
                return
            await interaction.response.defer(ephemeral=True)
            guild_data["users"].pop(str(self.target_id), None)
            cog._save_db()
            await self._refresh_panel()
            await interaction.followup.send(
                f"\u2796 Removed {self.target.mention} from the watch list", ephemeral=True
            )
            return
        await interaction.response.send_modal(WatchAddModal(self))

    @discord.ui.button(label="Add XP", emoji="\u2b06\ufe0f", style=discord.ButtonStyle.success, row=1)
    async def add_xp_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await interaction.response.send_modal(XPModal(self, True))

    @discord.ui.button(label="Remove XP", emoji="\u2b07\ufe0f", style=discord.ButtonStyle.secondary, row=1)
    async def remove_xp_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await interaction.response.send_modal(XPModal(self, False))

    @discord.ui.button(label="Log to GitHub", emoji="\U0001f4cb", style=discord.ButtonStyle.secondary, row=2)
    async def ghlog_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_action(interaction, "banlog"):
            return
        from cogs.GHLog import GHLogModal
        await interaction.response.send_modal(GHLogModal(self))

    @discord.ui.button(label="Wipe Data", emoji="\U0001f9f9", style=discord.ButtonStyle.danger, row=2)
    async def wipe_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await interaction.response.send_message(
            f"\u26a0\ufe0f Wipe **ALL** data for {self.target.mention}?\n"
            "This resets their XP/level, deletes all warns and notes, "
            "and removes them from the watch list. This can't be undone.",
            view=WipeConfirmView(self),
            ephemeral=True,
        )

    @discord.ui.button(label="History", emoji="\U0001f4dc", style=discord.ButtonStyle.secondary, row=2)
    async def history_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        data, urec = _mod_record(self.guild.id, self.target_id)
        cases = urec.get("cases", [])
        warns = urec.get("warns", [])
        notes = urec.get("notes", [])
        embed = discord.Embed(
            title=f"\U0001f4dc Case history — {self.target}",
            color=discord.Color.blurple(),
            timestamp=discord.utils.utcnow(),
        )
        embed.set_thumbnail(url=self.target.display_avatar.url)
        action_emoji = {
            "warn": "\u26a0\ufe0f", "timeout": "\u23f1\ufe0f", "untimeout": "\u23f1\ufe0f",
            "kick": "\U0001f462", "ban": "\U0001f528", "tempban": "\U0001f528",
            "unban": "\U0001f513", "clear": "\U0001f9f9", "wipe": "\U0001f9f9",
            "rename": "\u270f\ufe0f", "strip_roles": "\U0001f9f9",
        }
        if cases:
            lines = []
            for c in sorted(cases, key=lambda x: x.get("ts", 0), reverse=True)[:15]:
                ts = int(c.get("ts", 0))
                emo = action_emoji.get(c.get("action"), "\u2022")
                lines.append(
                    f"{emo} **{c.get('action')}** — <t:{ts}:R>\n"
                    f"> {c.get('reason', '')} _(by {c.get('mod_name', '?')})_"
                )
            embed.add_field(name=f"Cases ({len(cases)})", value="\n".join(lines)[:1024], inline=False)
        else:
            embed.add_field(name="Cases", value="No recorded actions.", inline=False)
        embed.add_field(name="Warns", value=str(len(warns)), inline=True)
        embed.add_field(name="Notes", value=str(len(notes)), inline=True)
        # Active tempban?
        try:
            _, tb = _tempban_data(self.guild.id)
            entry = tb.get(str(self.target_id))
            if entry:
                unban_ts = int(entry["unban_at"])
                embed.add_field(
                    name="Tempbanned", value=f"Until <t:{unban_ts}:F>", inline=True
                )
        except Exception:
            pass
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="Rename", emoji="\u270f\ufe0f", style=discord.ButtonStyle.secondary, row=2)
    async def rename_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        if self.guild.get_member(self.target_id) is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        await interaction.response.send_modal(RenameModal(self))

    @discord.ui.button(label="Strip Roles", emoji="\U0001f9f9", style=discord.ButtonStyle.danger, row=2)
    async def strip_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        member = self.guild.get_member(self.target_id)
        if member is None:
            await interaction.response.send_message(
                "\u274c That user isn't in the server anymore.", ephemeral=True
            )
            return
        roles = [r for r in member.roles if not r.is_default()]
        await interaction.response.send_message(
            f"\u26a0\ufe0f Strip **{len(roles)}** roles from {member.mention}?\n"
            + (", ".join(r.mention for r in roles[:10]) or "_They have no roles._"),
            view=StripRolesConfirmView(self),
            ephemeral=True,
        )


class AdminCog(commands.Cog):
    """Admin commands (e.g. clear_user)."""
    def __init__(self, client):
        self.bot = client
        self._board_tick = 0
        self._tempban_sweep.start()
        self._board_refresh.start()

    def cog_unload(self):
        self._tempban_sweep.cancel()
        self._board_refresh.cancel()

    @tasks.loop(minutes=1)
    async def _tempban_sweep(self):
        """Unban users whose tempban has expired."""
        try:
            data = load_json(MOD_DATA_FILE) or {}
        except Exception as e:
            print(f"[TEMPBAN] ERROR: could not load mod data for sweep: {e!r}")
            return
        now = time.time()
        changed = False
        for gid, grec in list(data.items()):
            tb = grec.get("tempbans") or {}
            for uid, entry in list(tb.items()):
                if entry.get("unban_at", 0) <= now:
                    guild = self.bot.get_guild(int(gid))
                    if guild is None:
                        # Bot is no longer in the server: nothing to unban.
                        # Drop the stale entry, but say so in the record
                        # instead of logging a phantom unban.
                        print(f"[TEMPBAN] Bot no longer in guild {gid}; dropping expired tempban for {uid}")
                        try:
                            _record_case(int(gid), int(uid), "unban",
                                         "Tempban expired (automatic; bot no longer in this server)", "AutoMod")
                        except Exception as e:
                            print(f"[TEMPBAN] ERROR: could not record unban case for {uid} in guild {gid}: {e!r}")
                        tb.pop(uid, None)
                        changed = True
                        continue
                    try:
                        await guild.unban(
                            discord.Object(id=int(uid)),
                            reason="Tempban expired (automatic)",
                        )
                    except discord.NotFound:
                        # Already unbanned (e.g. manual unban): the outcome
                        # is the same, so record it and drop the entry.
                        pass
                    except Exception as e:
                        print(f"[TEMPBAN] ERROR: failed to unban {uid} in guild {gid}: {e!r}; will retry next sweep")
                        continue
                    try:
                        _record_case(int(gid), int(uid), "unban",
                                     "Tempban expired (automatic)", "AutoMod")
                    except Exception as e:
                        print(f"[TEMPBAN] ERROR: could not record unban case for {uid} in guild {gid}: {e!r}")
                    # Log to moderation channel if the Logger is loaded.
                    try:
                        logger_cog = self.bot.get_cog("ModerationLogger")
                        if logger_cog is not None and guild is not None:
                            embed = discord.Embed(
                                title="\U0001f513 Tempban Expired",
                                description=f"<@{uid}> has been unbanned.",
                                color=discord.Color.green(),
                                timestamp=discord.utils.utcnow(),
                            )
                            embed.set_footer(text="Kush Bush Logger")
                            await logger_cog.send(guild, "moderation", embed)
                    except Exception:
                        pass
                    tb.pop(uid, None)
                    changed = True
                    _request_board_refresh(int(gid))
        if changed:
            try:
                save_json(MOD_DATA_FILE, data)
            except Exception:
                pass

    @_tempban_sweep.before_loop
    async def _before_tempban_sweep(self):
        await self.bot.wait_until_ready()
        self.cooldownRenamebot = {}  # Initialize cooldowns here
        self.COOLDOWN_SECONDS_Remame_bot = 500
        self.cooldownUserInfo = {}  # userinfo cooldowns: guild_id -> {user_id: timestamp}
        self.cooldownRenameuser = {}  # rename_user cooldowns: guild_id -> {user_id: timestamp}

        
        
     
        
    @tasks.loop(minutes=1)
    async def _board_refresh(self):
        """Refresh timeout boards: pending guilds every tick, all boards every 5 ticks."""
        try:
            pending = set(_BOARD_REFRESH_PENDING)
            _BOARD_REFRESH_PENDING.clear()
        except Exception:
            pending = set()
        self._board_tick += 1
        try:
            configs = await list_timeout_board_configs()
        except Exception as e:
            print(f"[TIMEOUT] ERROR: could not list board configs: {e!r}")
            configs = []
        targets = set(pending)
        if self._board_tick % 5 == 0:
            for cfg in configs:
                try:
                    targets.add(str(cfg.get("guild_id")))
                except Exception:
                    continue
        for gid in sorted(targets):
            try:
                guild = self.bot.get_guild(int(gid))
                if guild is None:
                    continue
                await _refresh_board(self.bot, guild)
            except Exception:
                print(f"[TIMEOUT] Board refresh failed for guild {gid}:")
                traceback.print_exc()

    @_board_refresh.before_loop
    async def _before_board_refresh(self):
        await self.bot.wait_until_ready()

    @commands.Cog.listener()
    async def on_member_update(self, before, after):
        try:
            await self._on_member_update(before, after)
        except Exception:
            print("[TIMEOUT] on_member_update failed:")
            traceback.print_exc()

    async def _on_member_update(self, before, after):
        """Notice timeouts applied/removed by hand in the Discord client."""
        if getattr(before, "guild", None) is None or getattr(after, "guild", None) is None:
            return
        before_until = getattr(before, "timed_out_until", None)
        after_until = getattr(after, "timed_out_until", None)
        if before_until == after_until:
            return
        guild = after.guild
        gid = guild.id
        uid = after.id
        if after_until is not None:
            # Timeout applied.
            try:
                until = after_until.timestamp()
            except Exception:
                return
            try:
                _, timeouts = _timeout_data(gid)
            except Exception:
                timeouts = {}
            existing = timeouts.get(str(uid)) or {}
            if existing and abs((existing.get("until", 0) or 0) - until) <= 10:
                return  # The bot's own apply; already recorded.
            actor, audit_reason = await _find_timeout_actor(guild, after)
            me = getattr(guild, "me", None)
            if actor is not None and me is not None and actor.id == me.id:
                return  # The bot's own action.
            mod_name = str(actor) if actor is not None else "Unknown"
            reason = audit_reason or "Timed out in Discord (manual)"
            try:
                data, timeouts = _timeout_data(gid)
                timeouts[str(uid)] = {
                    "until": until,
                    "reason": reason,
                    "mod_id": getattr(actor, "id", None),
                    "mod_name": mod_name,
                }
                _save_mod_data(data)
            except Exception as e:
                print(f"[TIMEOUT] Could not store manual timeout for {uid}: {e!r}")
                return
            try:
                _record_case(gid, uid, "timeout", reason, actor if actor is not None else "Unknown", {"duration": "manual"})
            except Exception as e:
                print(f"[TIMEOUT] Could not record manual timeout case for {uid}: {e!r}")
            _request_board_refresh(gid)
            try:
                await _refresh_board(self.bot, guild)
            except Exception:
                pass
            return
        # Timeout removed.
        try:
            _, timeouts = _timeout_data(gid)
        except Exception:
            return
        if str(uid) not in timeouts:
            return  # Nothing recorded; nothing to do.
        actor, _audit_reason = await _find_timeout_actor(guild, after)
        me = getattr(guild, "me", None)
        if actor is not None and me is not None and actor.id == me.id:
            return  # The bot's own removal; the panel already handled it.
        try:
            data, timeouts = _timeout_data(gid)
            timeouts.pop(str(uid), None)
            _save_mod_data(data)
        except Exception as e:
            print(f"[TIMEOUT] Could not clear manual untimeout for {uid}: {e!r}")
            return
        try:
            _record_case(gid, uid, "untimeout", "Timeout removed in Discord (manual)", actor if actor is not None else "Unknown")
        except Exception as e:
            print(f"[TIMEOUT] Could not record manual untimeout case for {uid}: {e!r}")
        _request_board_refresh(gid)
        try:
            await _refresh_board(self.bot, guild)
        except Exception:
            pass

    @staticmethod
    def _is_manager(ctx):
        """Manage Server or Administrator (same gate as the /userinfo panel)."""
        perms = ctx.author.guild_permissions
        return bool(perms.manage_guild or perms.administrator)

    @discord.slash_command(name="timeout", description="Time out a member (preset or custom duration).", guild_ids=GUILD_IDS)
    @extra_help("Time out a member with a preset length (light 5m, short 15m, medium 1h, long 1d, extended 1w, severe 2w) or a free-form duration like 1h30m (max 28d). Asks to replace when the member already has an active timeout.")
    async def timeout_cmd(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "Member to time out"),  # type: ignore
        preset: discord.Option(str, "Preset length", choices=[  # type: ignore
            discord.OptionChoice(name="Light \u2014 5 minutes", value="light"),
            discord.OptionChoice(name="Short \u2014 15 minutes", value="short"),
            discord.OptionChoice(name="Medium \u2014 1 hour", value="medium"),
            discord.OptionChoice(name="Long \u2014 1 day", value="long"),
            discord.OptionChoice(name="Extended \u2014 1 week", value="extended"),
            discord.OptionChoice(name="Severe \u2014 2 weeks", value="severe"),
        ], default=None, required=False),
        duration: discord.Option(str, "Custom duration, e.g. 1h30m (max 28d)", default=None, required=False),  # type: ignore
        reason: discord.Option(str, "Reason", default="No reason given", required=False),  # type: ignore
    ):
        """Time out a member with a preset or a custom duration."""
        if interaction.guild is None:
            await interaction.response.send_message("\u274c Use this in a server.", ephemeral=True)
            return
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(interaction, "timeout", _default_manage_or_admin):
            return
        duration_td, label = _resolve_timeout_duration(preset, duration)
        if duration_td is None:
            await interaction.response.send_message(f"\u274c {label}", ephemeral=True)
            return
        reason = (reason or "").strip() or "No reason given"
        guild = interaction.guild
        active_until = _active_timeout_until(guild, member)
        if active_until is not None:
            async def _apply_replace(inter):
                result = await _do_timeout(guild, member, duration_td, label, reason, interaction.user, True)
                try:
                    await inter.response.edit_message(content=result, view=None)
                except Exception:
                    pass
                try:
                    await _refresh_board(self.bot, guild)
                except Exception:
                    pass

            await interaction.response.send_message(
                f"\u23f1\ufe0f {member.mention} already has an active timeout "
                f"(until <t:{int(active_until)}:R>).\n"
                f"Replace it with `{label}`?\n**Reason:** {reason}",
                view=TimeoutReplaceView(guild.id, member.id, "", _apply_replace),
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=True)
        result = await _do_timeout(guild, member, duration_td, label, reason, interaction.user, True)
        try:
            await _refresh_board(self.bot, guild)
        except Exception:
            pass
        await interaction.followup.send(result, ephemeral=True)

    @discord.slash_command(name="timeout_board", description="Set up or remove the Active Timeouts board.", guild_ids=GUILD_IDS)
    @extra_help("Posts the Active Timeouts board in a channel (it lists every active Discord timeout and tempban, soonest expiry first, and refreshes itself). Run it again in another channel to move the board; run it with remove to take the board down.")
    async def timeout_board_cmd(
        self,
        interaction: discord.ApplicationContext,
        channel: discord.Option(discord.TextChannel, "Channel for the board", default=None, required=False),  # type: ignore
        remove: discord.Option(bool, "Remove the board", default=False, required=False),  # type: ignore
    ):
        """Set up, move, show, or remove the Active Timeouts board."""
        if interaction.guild is None:
            await interaction.response.send_message("\u274c Use this in a server.", ephemeral=True)
            return
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(interaction, "timeout_board", _default_manage_or_admin):
            return
        guild = interaction.guild
        if remove:
            try:
                cfg = await get_timeout_board_config(str(guild.id))
            except Exception:
                cfg = {}
            message_id = _safe_int((cfg or {}).get("message_id"))
            channel_id = _safe_int((cfg or {}).get("channel_id"))
            if message_id and channel_id:
                try:
                    old_channel = guild.get_channel(channel_id)
                    if old_channel is not None:
                        msg = await old_channel.fetch_message(message_id)
                        await msg.delete()
                except Exception:
                    pass
            try:
                await delete_timeout_board_config(str(guild.id))
            except Exception as e:
                await interaction.response.send_message(f"\u274c Could not remove the board: `{e}`", ephemeral=True)
                return
            await interaction.response.send_message("\U0001f5d1\ufe0f Timeout board removed.", ephemeral=True)
            return
        if channel is not None:
            try:
                await save_timeout_board_config(str(guild.id), {"channel_id": str(channel.id), "message_id": ""})
            except Exception as e:
                await interaction.response.send_message(f"\u274c Could not save the board setup: `{e}`", ephemeral=True)
                return
            ok = await _refresh_board(self.bot, guild)
            if ok:
                await interaction.response.send_message(f"\u23f1\ufe0f Active Timeouts board is live in {channel.mention}.", ephemeral=True)
            else:
                await interaction.response.send_message(f"\u274c Could not post the board in {channel.mention}. Check I can see it and send messages there.", ephemeral=True)
            return
        try:
            cfg = await get_timeout_board_config(str(guild.id))
        except Exception:
            cfg = {}
        channel_id = _safe_int((cfg or {}).get("channel_id"))
        if not channel_id:
            await interaction.response.send_message("No timeout board is set up. Run `/timeout_board` with a channel to set one up.", ephemeral=True)
            return
        ch = guild.get_channel(channel_id)
        entries = await _collect_board_entries(self.bot, guild)
        await interaction.response.send_message(
            f"\u23f1\ufe0f Timeout board is in {ch.mention if ch is not None else f'<#{channel_id}>'} "
            f"with {len(entries)} active timeout(s)/tempban(s).",
            ephemeral=True,
        )

    @discord.slash_command(name="clear_user", description="Clear messages from a user across one or all channels.")
    @extra_help("Clears messages from a specific user in one or all channels. You can specify a user by selecting them or by providing their ID. You can also choose a specific channel to clear messages from.")
    async def clear_user(
            self,
            interaction: discord.ApplicationContext,
            target_user: discord.Option(discord.User, "pick the user you wish to clear messages from ", default= None, required=False), # type: ignore
            user_id: discord.Option(str, "put in a users discord id if there no longer in the server", default= None, required=False), # type: ignore
            channel: discord.Option(discord.TextChannel, "pick a channel to clear messages from",  default= None, required=False),  # type: ignore
            amount: discord.Option (int, "set the amount of messages to clear from a user default 100",  default= 100, required=False) # type: ignore
        ):
            """Clear messages from a user in one or all channels."""
            from utils.permissions import check_slash_permission, _default_admin_only
            if not await check_slash_permission(interaction, "clear_user", _default_admin_only):
                return
            resolved_user_id = None
            user_display = None

            if target_user:
                resolved_user_id = target_user.id
                user_display = f"{target_user.display_name} ({target_user.name}#{target_user.discriminator})"
            elif user_id and user_id.isdigit():
                resolved_user_id = int(user_id)
                try:
                    user_obj = await self.bot.fetch_user(resolved_user_id)
                    user_display = f"ID `{resolved_user_id}`"
                except discord.NotFound:
                    await interaction.response.send_message("❌ User with the provided ID not found.", ephemeral=True)
                    return
            else:
                await interaction.response.send_message("❌ You must specify a user (via selection or ID).", ephemeral=True)
                return

            def is_target_user(msg):
                return msg.author.id == resolved_user_id

            channels_to_scan = (
                [channel] if channel
                else [
                    ch for ch in interaction.guild.text_channels
                    if ch.permissions_for(interaction.guild.me).read_message_history and
                    ch.permissions_for(interaction.guild.me).manage_messages
                ]
            )

            total_deleted = 0
            per_channel_summary = []

            await interaction.response.defer(ephemeral=True)

            for ch in channels_to_scan:
                try:
                    deleted = await ch.purge(limit=amount, check=is_target_user)
                except Exception as e:
                    per_channel_summary.append(f"Could not clear {ch.mention}: {e!r}")
                    continue
                total_deleted += len(deleted)
                per_channel_summary.append(f"Deleted {len(deleted)} messages in {ch.mention}")

            summary_message = f"✅ Finished clearing messages for {user_display}.\n" + "\n".join(per_channel_summary)
            await interaction.followup.send(summary_message, ephemeral=True)



   
    # User Info Command
    @discord.slash_command(name = "userinfo", description="View detailed info about a user.", guild_ids=GUILD_IDS)
    @extra_help("Mini admin panel: user card (account, server profile, XP/level, ban status, watch-list status, warns, notes) with Warn/Timeout/Kick/Ban/Clear/Notes/Watch/Add-XP/Remove-XP buttons. Ban/Timeout/Watch flip to Unban/Remove-timeout/Unwatch when active. Warn/Timeout/Kick/Ban ask for a reason, then a confirm step with a DM on/off toggle. The card refreshes itself after every action. Set test_mode to simulate actions, private to keep the card to yourself. Pick a member, or type a user ID, mention, or username. If no user is specified, it shows your own information.")
    async def userinfo(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "pick a server member", default=None), # type: ignore
        user: discord.Option(str, "or type a user ID, mention, or username", default=None), # type: ignore
        private: discord.Option(bool, "only you can see this card", default=True), # type: ignore
        test_mode: discord.Option(bool, "simulate mod actions instead of applying them", default=False), # type: ignore
        ):
        """View information about a user in the server."""
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "userinfo", _default_admin_only):
            return
        await interaction.response.defer(ephemeral=private)
        try:
            await self._userinfo_body(interaction, member, user, private, test_mode)
        except Exception as e:
            try:
                await interaction.followup.send(f"\u274c /userinfo failed: `{e}`", ephemeral=private)
            except Exception:
                pass
        return

    async def _resolve_userinfo_target(self, guild, query):
        """Turn a user ID, mention, or username into a Member/User.

        Returns (target, is_member). (None, False) when nothing matches.
        """
        digits = query.replace("<@", "").replace("<", "").replace("!", "").replace(">", "").strip()
        if digits.isdigit():
            uid = int(digits)
            target = guild.get_member(uid)
            if target is None:
                try:
                    target = await guild.fetch_member(uid)
                except (discord.NotFound, discord.Forbidden):
                    target = None
            if target is None:
                try:
                    target = await self.bot.fetch_user(uid)
                except Exception:
                    target = None
            if target is not None:
                return target, isinstance(target, discord.Member)
            return None, False
        # Username search across server members (exact match, then prefix).
        q = query.lstrip("@").lower()
        exact = [m for m in guild.members
                 if m.name.lower() == q or (m.display_name or "").lower() == q]
        if len(exact) == 1:
            return exact[0], True
        if not exact:
            starts = [m for m in guild.members
                      if m.name.lower().startswith(q) or (m.display_name or "").lower().startswith(q)]
            if len(starts) == 1:
                return starts[0], True
        return None, False

    async def _userinfo_body(self, interaction, member, user, private, test_mode):
        requester_id = interaction.author.id
        guild = interaction.guild
        guild_id = guild.id
        now = time.time()

        # Ensure guild key exists
        if guild_id not in self.cooldownUserInfo:
            self.cooldownUserInfo[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = self.cooldownUserInfo[guild_id]

        # Check cooldown
        if requester_id in user_cooldowns:
            elapsed = now - user_cooldowns[requester_id]
            if elapsed < USERINFO_COOLDOWN:
                remaining = round(USERINFO_COOLDOWN - elapsed, 1)
                await interaction.followup.send(f"\u23f3 You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[requester_id] = now

        # ---- Resolve the target ----
        # The member picker wins if both are given. Otherwise the text field
        # accepts a user ID, a mention, or a username. Nothing given = yourself.
        target = None
        is_member = False
        if member is not None:
            target = member
            is_member = True
        elif user:
            target, is_member = await self._resolve_userinfo_target(guild, user.strip())
            if target is None:
                await interaction.followup.send(
                    "\u274c I couldn't find that user. Pick a member, or use a user ID, a mention, or an exact username."
                )
                return
        else:
            target = interaction.author
            is_member = True

        watch_cog = self.bot.get_cog("WatchList")
        info_embed, state = await build_userinfo_embed(
            guild, target, is_member, test_mode, watch_cog,
            interaction.author.display_name,
        )
        is_banned = state["is_banned"]
        is_timed_out = state["is_timed_out"]
        watched = state["is_watched"]

        view = UserinfoModView(guild, target, is_member, test_mode=test_mode,
                                is_banned=is_banned, is_timed_out=is_timed_out,
                                watch_cog=watch_cog, is_watched=watched,
                                requester_name=interaction.author.display_name,
                                viewer=interaction.author)
        # Gray out buttons the requester may not use (custom perms for
        # warn/timeout/kick/ban/clear/banlog; Manage Server/Admin for
        # the rest) so they only see what they can actually do.
        await view._apply_viewer_permissions(interaction.author)
        view.message = await interaction.followup.send(
            embed=info_embed, view=view, ephemeral=private, wait=True
        )


    @discord.slash_command(name='remove_user_role', description="use this to remove a users role")
    @extra_help("Remove a role from a user in the server. You can specify a user by selecting them or by providing their ID. You can also choose a specific role to remove.")
    async def remove_user_role(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to remove a role from"), # type: ignore 
        role: discord.Option(discord.Role, "pick the role to remove from the user"), # type: ignore
        ):
        """Remove a role from a user in the server."""
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "remove_user_role", _default_admin_only):
            return
        if role is None: # This check might not be needed because if a role cannot be resolved, the command might not be triggered.
            await interaction.respond(f"Role not found.", ephemeral=True)
            return

        if role not in member.roles:
            await interaction.respond(f"{member.display_name} doesn't have the role '{role.name}'.", ephemeral=True) # Use role.name
            return

        try:
            await member.remove_roles(role)
            await interaction.respond(f"Removed role '{role.name}' from {member.display_name}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.respond(f"I don't have permission to remove the role '{role.name}'. Please ensure my role is above this role in the hierarchy.", ephemeral=True)
        except Exception as e:
            await interaction.respond(f"An error occurred: {e}")


    @discord.slash_command(name="add_user_role", description="use this to give a role to a user in the server")
    @extra_help("Add a role to a user in the server. You can specify a user by selecting them or by providing their ID. You can also choose a specific role to add.")
    async def add_user_role(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to add a role from"), # type: ignore  
        role: discord.Option(discord.Role,"this is is used to pick the role to set for the user"), # type: ignore
        ):
        """Add a role to a user in the server.""" 
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "add_user_role", _default_admin_only):
            return
        if role is None:
            await interaction.response.send_message(f"Role not found.", ephemeral=True) # Changed from respond to response.send_message
            return

        if role in member.roles:
            await interaction.response.send_message(f"{member.display_name} already has the role '{role.name}'.", ephemeral=True) # Changed from respond to response.send_message
            return
        
        try:
            await member.add_roles(role)
            await interaction.response.send_message(f"Successfully added the role '{role.name}' to {member.display_name}.", ephemeral=True) # Success message
        except discord.Forbidden:   
            await interaction.response.send_message(f"I don't have permission to add the role '{role.name}'. Please ensure my role is above this role in the hierarchy.", ephemeral=True) # Changed from respond to response.send_message
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True) # Changed from respond to response.send_message and added ephemeral=True

        
        
        
        
        
        
      
    
    @discord.slash_command(name="rename_bot", description="used by the admins to change the name of the bot in there discord server")
    @extra_help("Rename the bot in your server. You can set a new nickname for the bot, but ensure it doesn't violate Discord's naming policies.")
    async def rename_bot(
        self,
        interaction: discord.ApplicationContext,
        new_nick: str = discord.Option(str, description="set the name of the bot") # Corrected Option usage
        ):
        """Rename the bot in the server."""
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "rename_bot", _default_admin_only):
            return
        await interaction.response.defer()
        user_id = interaction.author.id
        guild_id = interaction.guild.id
        now = time.time()

        # Ensure guild key exists
        if guild_id not in self.cooldownRenamebot:
            self.cooldownRenamebot[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = self.cooldownRenamebot[guild_id]

        # Check cooldown
        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < self.COOLDOWN_SECONDS_Remame_bot:
                remaining = round(self.COOLDOWN_SECONDS_Remame_bot - elapsed, 1)
                await interaction.followup.send(f"⏳ You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[user_id] = now
        try:
            # Need to get the bot's member object in the guild
            bot_member = interaction.guild.me
            await bot_member.edit(nick=new_nick) # Use the bot's member object to change the nickname
            await interaction.followup.send(f"Bot renamed to **{new_nick}** in **{interaction.guild.name}**") # Use followup.send after deferring
        except discord.Forbidden: # Handle specific permission error
            await interaction.followup.send("I couldn't rename myself. Please check my permissions (Manage Nicknames)!") # Provide helpful error message
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}") # Use followup.send for general errors as well
          

    @discord.slash_command(name="rename_user", description="used by the admins to change the name a user in there discord server")
    @extra_help("Rename a user in your server. You can set a new nickname for the user, but ensure it doesn't violate Discord's naming policies.")
    async def rename_user(
        self, interaction: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "pick the name of the user you want to change"), # type: ignore 
        new_nick: discord.Option(str, "set the name of the user ") # type: ignore
        ):
        """Rename a user in the server."""
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "rename_user", _default_admin_only):
            return
        COOLDOWN_SECONDS_Rename_User = 5
        await interaction.response.defer()
        user_id = interaction.author.id
        guild_id = interaction.guild.id
        now = time.time()

        # Ensure guild key exists
        if guild_id not in self.cooldownRenameuser:
            self.cooldownRenameuser[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = self.cooldownRenameuser[guild_id]

        # Check cooldown
        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < COOLDOWN_SECONDS_Rename_User:
                remaining = round(COOLDOWN_SECONDS_Rename_User - elapsed, 1)
                await interaction.followup.send(f"⏳ You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[user_id] = now
        try:
            await member.edit(nick=new_nick)
            await interaction.send(f"user name changed to **{member.mention}** in **{interaction.guild.name}**")
        except Exception as e:
            await interaction.send("can't find the user in the discord")



    @discord.slash_command(name="reset_user_name", description="used by the admins to reset the useers name")
    @extra_help("Reset a user's nickname in your server. This will remove any custom nickname they have set.")
    async def reset_user_name(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "Pick the user to reset there name ") # type: ignore
        ):
        """Reset a user's nickname in the server."""
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "reset_user_name", _default_admin_only):
            return
        try:
            await member.edit(nick=None)
            await interaction.respond(f"{member.mention}'s nickname was reset in **{interaction.guild.name}**.")
        except Exception:
            await interaction.respond("I couldn't reset that user's nickname. Do I have permission?")
     
        
    @discord.slash_command(name="shutdown_bot",description="Make the bot shutdown.",)
    @extra_help("Shuts down the bot. Use this command with caution as it will stop the bot from running until restarted.")
    @is_owner()
    async def shutdown(self, interaction: discord.ApplicationContext) -> None:
        """Shuts down the bot."""
        embed = discord.Embed(description="Shutting down. Bye! :wave:", color=0xBEBEFE)
        await interaction.send(embed=embed)
        await self.bot.close()
        # Exit code 0: the watchdog stays stopped (clean shutdown).
        # os._exit, not sys.exit: a SystemExit raised inside an
        # event-loop task is swallowed by the loop and the process
        # would keep running; the gateway is already closed here.
        os._exit(0)

    
    
    @discord.slash_command(name="restart_bot", description="Restarts the bot.")
    @extra_help("Restarts the bot. Use this command with caution as it will stop the bot and start it again.")
    @is_owner()
    async def restart(self, ctx: discord.ApplicationContext):
        """Restarts the bot."""
        embed = discord.Embed(description="Restarting... Be right back! 🔁", color=0xBEBEFE)
        await ctx.respond(embed=embed)

        # Close the gateway cleanly, then exit with code 42 so the
        # watchdog relaunches the bot. Do NOT spawn a new process
        # from inside the bot (that was the old P1-19 bug: the child
        # inherited the parent's locks/handles).
        await self.bot.close()
        # os._exit, not sys.exit: a SystemExit raised inside an
        # event-loop task is swallowed by the loop and the process
        # would keep running; the gateway is already closed here.
        os._exit(42)
    

        

    @discord.slash_command(name="restart_web", description="Restarts the website.")
    @extra_help("Restarts the website (web dashboard). Use this command with caution as it will stop the website and start it again.")
    @is_owner()
    async def restart_web(self, ctx: discord.ApplicationContext):
        """Restarts the website (web dashboard)."""
        secret = os.getenv("BRIDGE_SECRET")
        if not secret:
            embed = discord.Embed(
                description="I can't restart the website: BRIDGE_SECRET is not set in the bot's .env.",
                color=0xBEBEFE,
            )
            await ctx.respond(embed=embed, ephemeral=True)
            return
        embed = discord.Embed(description="Restarting the website... Be right back! 🔁", color=0xBEBEFE)
        await ctx.respond(embed=embed)
        base = os.getenv("WEB_BASE_URL", "http://127.0.0.1:5000").rstrip("/")
        url = base + "/api/internal/website/restart"
        try:
            timeout = aiohttp.ClientTimeout(total=10)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(url, headers={"X-Bridge-Secret": secret}) as resp:
                    status = resp.status
        except (aiohttp.ClientError, asyncio.TimeoutError):
            embed = discord.Embed(
                description="I couldn't reach the website (it may already be down) — restart it by hand: `sudo systemctl restart kushweb.service` on the server, or close and re-run `run_web.bat` on Windows.",
                color=0xBEBEFE,
            )
            await ctx.edit(embed=embed)
            return
        if status == 200:
            embed = discord.Embed(
                description="Website is restarting — it'll be back in a few seconds.",
                color=0xBEBEFE,
            )
        elif status == 401:
            embed = discord.Embed(
                description="The website refused the restart (bridge secret mismatch) — check BRIDGE_SECRET matches on both sides.",
                color=0xBEBEFE,
            )
        elif status == 503:
            embed = discord.Embed(
                description="The website refused the restart: BRIDGE_SECRET is not set on the website side.",
                color=0xBEBEFE,
            )
        else:
            embed = discord.Embed(
                description="The website answered with an unexpected status (%s) — check the website log." % status,
                color=0xBEBEFE,
            )
        await ctx.edit(embed=embed)

def setup(client):
    client.add_cog(AdminCog(client))

