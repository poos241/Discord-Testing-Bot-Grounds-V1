# cogs/admin_cog.py
import time
import re
from datetime import datetime, timezone, timedelta
import discord
from discord.ext import commands
import os
import sys
import subprocess
import asyncio
from config import  GUILD_IDS, admin_required, is_owner, load_json, save_json, autocomplete_commands , extra_help

USERINFO_COOLDOWN = 60


# ---------------------------------------------------------------------------
# /userinfo mini mod panel: Timeout / Kick / Ban buttons (+ test mode)
# ---------------------------------------------------------------------------

def parse_mod_duration(text):
    """Parse '10m', '2h', '1d', '30s', '1w' (bare number = minutes) -> timedelta.

    Returns None when the text is invalid or outside Discord's 28-day cap.
    """
    m = re.match(r"^\s*(\d+)\s*([smhdwSMHDW]?)\s*$", text or "")
    if not m:
        return None
    amount = int(m.group(1))
    unit = (m.group(2) or "m").lower()
    seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
    delta = timedelta(seconds=seconds)
    if delta <= timedelta(0) or delta > timedelta(days=28):
        return None
    return delta


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

    async def callback(self, interaction: discord.Interaction):
        reason = (self.children[0].value or "").strip() or "No reason given"
        days_raw = (self.children[1].value or "0").strip()
        days = int(days_raw) if days_raw.isdigit() else -1
        if days < 0 or days > 7:
            await interaction.response.send_message(
                "\u274c Message-delete days must be 0\u20137.", ephemeral=True
            )
            return
        mention = self.panel.target.mention
        if self.panel.test_mode:
            await interaction.response.send_message(
                f"\U0001f9ea TEST \u2014 would ban {mention} (delete {days}d of messages)\n**Reason:** {reason}",
                ephemeral=True,
            )
            return
        summary = (f"\U0001f528 Ban {mention} (delete {days}d of messages)\n"
                   f"**Reason:** {reason}")
        await interaction.response.send_message(
            f"{summary}\n\n_Use the toggle to choose whether they get a DM, then confirm._",
            view=ModConfirmView(
                self.panel, "ban", {"reason": reason, "delete_days": days}, summary
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
        await interaction.followup.send(
            f"\U0001f9f9 Cleared **{total}** messages from {mention} in {where_desc}.\n{lines}",
            ephemeral=True,
        )


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


async def _dm_target(target, text):
    """Try to DM someone. Returns True on success, False when DMs are closed."""
    try:
        await target.send(text)
        return True
    except Exception:
        return False


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
            return
        try:
            from data.DB.Storage.storage import get_levels, save_levels
            if self.adding:
                from cogs.Level_system import award_xp
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
        await interaction.edit_original_response(content=result, view=None)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, row=1)
    async def cancel_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if self.done:
            return
        self.done = True
        await interaction.response.edit_message(content="\u274c Cancelled.", view=None)


class UserinfoModView(discord.ui.View):
    """Mini admin panel attached to the /userinfo card."""

    def __init__(self, guild, target, is_member, test_mode=False, is_banned=False,
                 is_timed_out=False, watch_cog=None, is_watched=False,
                 requester_name=""):
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
        self.message = None
        self._sync_buttons({
            "is_member": is_member,
            "is_banned": is_banned,
            "is_timed_out": is_timed_out,
            "is_watched": is_watched,
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
            n = len(urec["warns"])
            return f"\u26a0\ufe0f Warned {target.mention} (warn #{n})\n**Reason:** {reason}{note}"

        member = guild.get_member(self.target_id)
        if member is None:
            return "\u274c That user isn't in the server anymore."

        if action == "timeout":
            duration = params["duration"]
            raw = params["duration_str"]
            note = ""
            if dm_enabled:
                ok = await _dm_target(
                    member,
                    f"\u23f1\ufe0f You've been timed out in **{guild.name}** for `{raw}`\n**Reason:** {reason}",
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
            return f"\u23f1\ufe0f Timed out {member.mention} for `{raw}`\n**Reason:** {reason}{note}"

        if action == "kick":
            note = ""
            if dm_enabled:
                ok = await _dm_target(
                    member,
                    f"\U0001f462 You've been kicked from **{guild.name}**\n**Reason:** {reason}",
                )
                note = f"\n{dm_note(ok)}"
            try:
                await member.kick(reason=audit)
            except discord.Forbidden:
                return "\u274c I can't kick that user \u2014 is my role above theirs?"
            except Exception as e:
                return f"\u274c Kick failed: `{e}`"
            return f"\U0001f462 Kicked {member.mention}\n**Reason:** {reason}{note}"

        if action == "ban":
            days = params["delete_days"]
            note = ""
            if dm_enabled:
                ok = await _dm_target(
                    target,
                    f"\U0001f528 You've been banned from **{guild.name}**\n**Reason:** {reason}",
                )
                note = f"\n{dm_note(ok)}"
            try:
                await guild.ban(target, reason=audit, delete_message_days=days)
            except discord.Forbidden:
                return "\u274c I can't ban that user \u2014 is my role above theirs?"
            except Exception as e:
                return f"\u274c Ban failed: `{e}`"
            return f"\U0001f528 Banned {target.mention}\n**Reason:** {reason}{note}"

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

    @discord.ui.button(label="Warn", emoji="\u26a0\ufe0f", style=discord.ButtonStyle.secondary, row=0)
    async def warn_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
            return
        await interaction.response.send_modal(WarnModal(self))

    @discord.ui.button(label="Timeout", emoji="\u23f1\ufe0f", style=discord.ButtonStyle.primary, row=0)
    async def timeout_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
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
            await self._refresh_panel()
            await interaction.followup.send(
                f"\u23f1\ufe0f Removed timeout from {member.mention}", ephemeral=True
            )
            return
        await interaction.response.send_modal(TimeoutModal(self, member))

    @discord.ui.button(label="Kick", emoji="\U0001f462", style=discord.ButtonStyle.danger, row=0)
    async def kick_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
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
        if not await self._check_admin(interaction):
            return
        if self.is_banned:
            if self.test_mode:
                await interaction.response.send_message(
                    f"\U0001f9ea TEST \u2014 would unban {self.target.mention}",
                    ephemeral=True,
                )
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
            await self._refresh_panel()
            await interaction.followup.send(
                f"\U0001f513 Unbanned {self.target.mention}", ephemeral=True
            )
            return
        await interaction.response.send_modal(BanModal(self))

    @discord.ui.button(label="Clear", emoji="\U0001f9f9", style=discord.ButtonStyle.secondary, row=0)
    async def clear_button(self, button: discord.ui.Button, interaction: discord.Interaction):
        if not await self._check_admin(interaction):
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


class AdminCog(commands.Cog):
    """Admin commands (e.g. clear_user)."""
    def __init__(self, client):
        self.bot = client
        self.cooldownRenamebot = {}  # Initialize cooldowns here
        self.COOLDOWN_SECONDS_Remame_bot = 500
        self.cooldownUserInfo = {}  # userinfo cooldowns: guild_id -> {user_id: timestamp}
        self.cooldownRenameuser = {}  # rename_user cooldowns: guild_id -> {user_id: timestamp}

        
        
     
        
    @discord.slash_command(name="clear_user", description="Clear messages from a user across one or all channels.")
    @extra_help("Clears messages from a specific user in one or all channels. You can specify a user by selecting them or by providing their ID. You can also choose a specific channel to clear messages from.")
    @admin_required()
    async def clear_user(
            self,
            interaction: discord.ApplicationContext,
            target_user: discord.Option(discord.User, "pick the user you wish to clear messages from ", default= None, required=False), # type: ignore
            user_id: discord.Option(str, "put in a users discord id if there no longer in the server", default= None, required=False), # type: ignore
            channel: discord.Option(discord.TextChannel, "pick a channel to clear messages from",  default= None, required=False),  # type: ignore
            amount: discord.Option (int, "set the amount of messages to clear from a user default 100",  default= 100, required=False) # type: ignore
        ):
            """Clear messages from a user in one or all channels."""
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
                    await interaction.followup.send("❌ User with the provided ID not found.", ephemeral=True)
                    return
            else:
                await interaction.followup.send("❌ You must specify a user (via selection or ID).", ephemeral=True)
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
                deleted = await ch.purge(limit=amount, check=is_target_user)
                total_deleted += len(deleted)
                per_channel_summary.append(f"Deleted {len(deleted)} messages in {ch.mention}")

            summary_message = f"✅ Finished clearing messages for {user_display}.\n" + "\n".join(per_channel_summary)
            await interaction.followup.send(summary_message, ephemeral=True)



   
    # User Info Command
    @discord.slash_command(name = "userinfo", description="View detailed info about a user.", guild_ids=GUILD_IDS)
    @extra_help("Mini admin panel: user card (account, server profile, XP/level, ban status, watch-list status, warns, notes) with Warn/Timeout/Kick/Ban/Clear/Notes/Watch/Add-XP/Remove-XP buttons. Ban/Timeout/Watch flip to Unban/Remove-timeout/Unwatch when active. Warn/Timeout/Kick/Ban ask for a reason, then a confirm step with a DM on/off toggle. The card refreshes itself after every action. Set test_mode to simulate actions, private to keep the card to yourself. Pick a member, or type a user ID, mention, or username. If no user is specified, it shows your own information.")
    @admin_required()
    async def userinfo(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "pick a server member", default=None), # type: ignore
        user: discord.Option(str, "or type a user ID, mention, or username", default=None), # type: ignore
        private: discord.Option(bool, "only you can see this card", default=True), # type: ignore
        test_mode: discord.Option(bool, "simulate mod actions instead of applying them", default=False), # type: ignore
        ):
        """View information about a user in the server."""
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
                                requester_name=interaction.author.display_name)
        view.message = await interaction.followup.send(
            embed=info_embed, view=view, ephemeral=private, wait=True
        )


    @discord.slash_command(name='remove_user_role', description="use this to remove a users role")
    @extra_help("Remove a role from a user in the server. You can specify a user by selecting them or by providing their ID. You can also choose a specific role to remove.")
    @admin_required() 
    async def remove_user_role(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to remove a role from"), # type: ignore 
        role: discord.Option(discord.Role, "pick the role to remove from the user"), # type: ignore
        ):
        """Remove a role from a user in the server."""
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
    @admin_required()  
    async def add_user_role(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to add a role from"), # type: ignore  
        role: discord.Option(discord.Role,"this is is used to pick the role to set for the user"), # type: ignore
        ):
        """Add a role to a user in the server.""" 
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
    @admin_required()
    async def rename_bot(
        self,
        interaction: discord.ApplicationContext,
        new_nick: str = discord.Option(str, description="set the name of the bot") # Corrected Option usage
        ):
        """Rename the bot in the server."""
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
    @admin_required()
    async def rename_user(
        self, interaction: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "pick the name of the user you want to change"), # type: ignore 
        new_nick: discord.Option(str, "set the name of the user ") # type: ignore
        ):
        """Rename a user in the server."""
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
    @admin_required()
    async def reset_user_name(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "Pick the user to reset there name ") # type: ignore
        ):
        """Reset a user's nickname in the server."""
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

    
    
    @discord.slash_command(name="restart_bot", description="Restarts the bot.")
    @extra_help("Restarts the bot. Use this command with caution as it will stop the bot and start it again.")
    @is_owner()
    async def restart(self, ctx: discord.ApplicationContext):
        """Restarts the bot."""
        embed = discord.Embed(description="Restarting... Be right back! 🔁", color=0xBEBEFE)
        await ctx.respond(embed=embed)

        # Windows-friendly restart using subprocess
        python = sys.executable
        subprocess.Popen([python] + sys.argv)

        await self.bot.close()
    

        

def setup(client):
    client.add_cog(AdminCog(client))

