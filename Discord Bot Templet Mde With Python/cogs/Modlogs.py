"""Modlog viewer + edit cog (built 2026-11-02).

Ported from the Little Haven bot's modlog system, integrated into
this bot's EXISTING moderation store -- there is no parallel store
and no new table. Everything reads and writes the same mod_data
(via _mod_record / _save_mod_data in cogs/admin_cog.py) that the
/userinfo panel, warns, kicks, bans and timeouts already use.

What it adds:
- /modlogs -- paginated viewer of moderation cases, with filters
  (member, user id, action type, before/after date). No filter
  shows the most recent cases across the guild.
- /modlogs_recap -- per-user counts by action type, most recent
  case, and active tempban status.
- /modlogs_edit -- pick one of a user's most recent cases from a
  select menu, then edit its reason (modal) or delete it (with a
  confirmation screen first). Edits/deletes are logged to the
  Logger's moderation log channel when one is configured.
- /mod_actions -- every action performed BY a given moderator.

Design notes (read before changing this file):
- Cases have no id in this bot. A case is displayed numbered per
  user, most recent first (#1 = newest), and is resolved at click
  time by (user id, list index, timestamp, action, moderator).
  The resolve re-loads the record and checks the case at that
  index still matches; if the list shifted, it searches for the
  unique case with the same timestamp + action + moderator. If it
  cannot be found, the action refuses cleanly instead of touching
  the wrong case. Never delete by bare index without that check.
- Reads never create mod records: all read paths use load_json +
  .get() chains. Only _mod_record (setdefault) is used on the
  write path, after a case has already been resolved.
- Warns live in two places: a "warn" action appends to BOTH the
  user's "cases" list and their "warns" list (see admin_cog.py).
  Editing or deleting a warn case mirrors the change into the
  matching "warns" entry (same moderator, same reason, timestamp
  within 10 seconds) so the panel's warn count stays in step.
  If no matching warns entry is found, only the case changes.
- Gates match the /userinfo panel: Manage Server or Administrator
  for every command here (see _is_manager). The Haven bot's
  /modActions was OWNERONLY; that is deliberately NOT copied --
  a moderator-tier gate is the right level for a read view.
- Edit/delete logging reuses the Logger's moderation log channel
  (cogs/Logger/utils.py send_log, log_type "moderation"). If no
  channel is configured there, send_log quietly does nothing and
  the ephemeral confirmation is the trace.
- Every view callback re-checks the clicker's permissions and is
  wrapped so a failure is logged and never kills the flow.
"""

import traceback
from datetime import datetime, timezone

import discord
from discord.ext import commands

from config import GUILD_IDS, load_json
from cogs.admin_cog import MOD_DATA_FILE, _mod_record, _save_mod_data

PAGE_SIZE = 5
SELECT_LIMIT = 25
GUILD_SCAN_CAP = 250
WARN_MIRROR_WINDOW = 10  # seconds; warns entry vs case timestamps

ACTION_TYPES = (
    "warn", "timeout", "untimeout", "kick", "ban",
    "tempban", "unban", "clear", "strip_roles", "wipe",
)
TYPE_CHOICES = [
    discord.OptionChoice(name=action.title().replace("_", " "), value=action)
    for action in ACTION_TYPES
]

ACTION_EMOJI = {
    "warn": "\u26a0\ufe0f", "timeout": "\u23f1\ufe0f", "untimeout": "\u23f1\ufe0f",
    "kick": "\U0001f462", "ban": "\U0001f528", "tempban": "\U0001f528",
    "unban": "\U0001f513", "clear": "\U0001f9f9", "wipe": "\U0001f9f9",
    "rename": "\u270f\ufe0f", "strip_roles": "\U0001f9f9",
}


def _is_manager(ctx):
    """Manage Server or Administrator -- same gate as the /userinfo panel.

    Works for both slash-command contexts (ctx.author) and component
    interactions (interaction.user).
    """
    if getattr(ctx, "guild", None) is None:
        return False
    user = getattr(ctx, "author", None) or getattr(ctx, "user", None)
    if user is None:
        return False
    perms = user.guild_permissions
    return bool(perms.manage_guild or perms.administrator)


def _safe_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _action_base(action):
    """Canonical type for a stored action string.

    Tempbans are stored with their duration in the label, e.g.
    "tempban (7d)", so the base type is the first word.
    """
    return (action or "").strip().split(" ", 1)[0].lower()


def _load_guild(guild_id):
    """Read-only load of one guild's mod_data. Never creates records."""
    try:
        data = load_json(MOD_DATA_FILE) or {}
    except Exception as e:
        print(f"[MODLOG] Could not load mod data: {e!r}")
        return {}
    if not isinstance(data, dict):
        return {}
    grec = data.get(str(guild_id), {})
    return grec if isinstance(grec, dict) else {}


def _case_number(cases, index):
    """Per-user case number: most recent case is #1."""
    return len(cases) - index


def _collect_cases(guild_id, target_id=None, moderator_id=None,
                   moderator_name=None, type_filter=None,
                   before_ts=None, after_ts=None, cap=None):
    """Gather cases matching the filters, newest first.

    Returns a list of dicts: {user_id, index, case, number, ts}.
    Read-only: never creates mod records.
    """
    grec = _load_guild(guild_id)
    out = []
    user_ids = [str(target_id)] if target_id is not None else list(grec.keys())
    for uid in user_ids:
        urec = grec.get(uid)
        if not isinstance(urec, dict):
            continue
        cases = urec.get("cases", [])
        if not isinstance(cases, list):
            continue
        for index, case in enumerate(cases):
            if not isinstance(case, dict):
                continue
            ts = case.get("ts", 0) or 0
            try:
                ts = float(ts)
            except (TypeError, ValueError):
                ts = 0
            if type_filter and _action_base(case.get("action")) != type_filter:
                continue
            if before_ts is not None and not ts < before_ts:
                continue
            if after_ts is not None and not ts >= after_ts:
                continue
            if moderator_id is not None:
                mid = case.get("mod_id")
                if mid != moderator_id and not (
                    mid is None and moderator_name
                    and case.get("mod_name") == moderator_name
                ):
                    continue
            out.append({
                "user_id": uid,
                "index": index,
                "case": case,
                "number": _case_number(cases, index),
                "ts": ts,
            })
    out.sort(key=lambda item: item["ts"], reverse=True)
    if cap is not None:
        out = out[:cap]
    return out


def _parse_date(text):
    """Parse a YYYY-MM-DD date into a UTC start-of-day epoch.

    Returns (epoch, None) or (None, error message).
    """
    raw = (text or "").strip()
    try:
        day = datetime.strptime(raw, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    except ValueError:
        return None, (
            f'"{raw}" is not a date. Use YYYY-MM-DD, e.g. 2026-10-01.'
        )
    return day.timestamp(), None


def _format_case(guild, entry):
    """One case as an embed field (name, value)."""
    case = entry["case"]
    action = case.get("action", "?")
    ts = int(entry["ts"])
    emo = ACTION_EMOJI.get(_action_base(action), "\u2022")
    member = guild.get_member(_safe_int(entry["user_id"]))
    target = member.mention if member else f"<@{entry['user_id']}>"
    reason = (case.get("reason") or "").strip() or "No reason given"
    if len(reason) > 300:
        reason = reason[:297] + "..."
    mod = case.get("mod_name") or "?"
    name = f"#{entry['number']} {emo} {action} — <t:{ts}:D>"
    value = (
        f"**Target:** {target} (`{entry['user_id']}`)\n"
        f"**Reason:** {reason}\n"
        f"**By:** {mod} • <t:{ts}:R>"
    )
    return name, value


def _case_key(entry):
    """Opaque identity for a case, carried in select values."""
    case = entry["case"]
    mod_id = case.get("mod_id") or 0
    return f"{entry['user_id']}:{entry['index']}:{int(entry['ts'])}:{mod_id}"


def _parse_case_key(value):
    parts = (value or "").split(":")
    if len(parts) != 4:
        return None
    uid, index, ts, mod_id = parts
    index = _safe_int(index)
    ts = _safe_int(ts)
    mod_id = _safe_int(mod_id)
    if index is None or ts is None or mod_id is None:
        return None
    return {"user_id": uid, "index": index, "ts": ts, "mod_id": mod_id}


def _resolve_case(guild_id, key):
    """Re-find a case at click time. Returns (data, urec, cases, index, case)
    or (None, None, None, None, None) when the case is gone or changed.

    The case at the stored index must still match (timestamp within
    2 seconds, same action base, same moderator); otherwise the whole
    list is searched for the unique case with that timestamp + action
    + moderator. A bare index is never trusted on its own.
    """
    try:
        data = load_json(MOD_DATA_FILE) or {}
    except Exception as e:
        print(f"[MODLOG] Could not load mod data for resolve: {e!r}")
        return None, None, None, None, None
    grec = data.get(str(guild_id), {})
    urec = grec.get(str(key["user_id"]), {}) if isinstance(grec, dict) else {}
    if not isinstance(urec, dict):
        return None, None, None, None, None
    cases = urec.get("cases", [])
    if not isinstance(cases, list):
        return None, None, None, None, None

    def _matches(case, index):
        if not isinstance(case, dict):
            return False
        try:
            ts = float(case.get("ts", 0) or 0)
        except (TypeError, ValueError):
            return False
        return abs(ts - key["ts"]) < 2

    index = key["index"]
    if 0 <= index < len(cases) and _matches(cases[index], index):
        return data, urec, cases, index, cases[index]
    found = [i for i, c in enumerate(cases) if _matches(c, i)]
    if len(found) == 1:
        return data, urec, cases, found[0], cases[found[0]]
    return None, None, None, None, None


def _mirror_warn(urec, case, new_reason=None, delete=False):
    """Mirror a warn-case edit/delete into the parallel "warns" list.

    A warn writes both a case and a warns entry (same moderator, same
    reason, timestamps seconds apart). Find the closest matching warns
    entry and apply the same change. No match: leave warns alone.
    """
    if _action_base(case.get("action")) != "warn":
        return
    warns = urec.get("warns", [])
    if not isinstance(warns, list) or not warns:
        return
    old_reason = case.get("reason") or ""
    mod_id = case.get("mod_id")
    try:
        ts = float(case.get("ts", 0) or 0)
    except (TypeError, ValueError):
        ts = 0
    best = None
    best_gap = None
    for i, w in enumerate(warns):
        if not isinstance(w, dict):
            continue
        if w.get("mod_id") != mod_id or (w.get("reason") or "") != old_reason:
            continue
        try:
            gap = abs(float(w.get("ts", 0) or 0) - ts)
        except (TypeError, ValueError):
            continue
        if gap <= WARN_MIRROR_WINDOW and (best_gap is None or gap < best_gap):
            best, best_gap = i, gap
    if best is None:
        return
    if delete:
        del warns[best]
    else:
        warns[best]["reason"] = new_reason


def _apply_edit(guild_id, key, new_reason):
    """Change a case's reason. Returns (ok, message, case_copy or None)."""
    data, urec, cases, index, case = _resolve_case(guild_id, key)
    if case is None:
        return False, (
            "That case changed or was removed since the list was built. "
            "Run /modlogs_edit again to pick it fresh."
        ), None
    old = dict(case)
    _mirror_warn(urec, case, new_reason=new_reason)
    case["reason"] = new_reason
    try:
        _save_mod_data(data)
    except Exception as e:
        print(f"[MODLOG] Could not save edited case: {e!r}")
        return False, "Could not save that edit — the database write failed.", None
    return True, "Case updated.", old


def _apply_delete(guild_id, key):
    """Delete a case. Returns (ok, message, case_copy or None)."""
    data, urec, cases, index, case = _resolve_case(guild_id, key)
    if case is None:
        return False, (
            "That case changed or was removed since the list was built. "
            "Run /modlogs_edit again to pick it fresh."
        ), None
    old = dict(case)
    _mirror_warn(urec, case, delete=True)
    del cases[index]
    try:
        _save_mod_data(data)
    except Exception as e:
        print(f"[MODLOG] Could not save deleted case: {e!r}")
        return False, "Could not save that delete — the database write failed.", None
    return True, "Case deleted.", old


async def _log_mod_action(bot, guild_id, title, description, color):
    """Best-effort embed to the Logger's moderation log channel.

    Quietly does nothing when no channel is configured; never raises.
    """
    try:
        from cogs.Logger.utils import send_log
        embed = discord.Embed(title=title, description=description, color=color)
        await send_log(bot, guild_id, "moderation", embed)
    except Exception as e:
        print(f"[MODLOG] Could not log mod action to moderation channel: {e!r}")


# ---------- views ----------

class ModlogPagerView(discord.ui.View):
    """Prev/Next pager over collected cases (5 per page)."""

    def __init__(self, guild, items, title):
        super().__init__(timeout=300)
        self.guild = guild
        self.items = items
        self.title = title
        self.page = 0
        self.message = None
        self._refresh_buttons()

    @property
    def page_count(self):
        return max(1, (len(self.items) + PAGE_SIZE - 1) // PAGE_SIZE)

    def _refresh_buttons(self):
        self.prev_button.disabled = self.page <= 0
        self.next_button.disabled = self.page >= self.page_count - 1

    def build_embed(self):
        total = len(self.items)
        if total == 0:
            embed = discord.Embed(
                title=self.title,
                description="No cases found.",
                color=discord.Color.blurple(),
            )
            embed.set_footer(text="Page 1/1 • 0 cases")
            return embed
        start = self.page * PAGE_SIZE
        page_items = self.items[start:start + PAGE_SIZE]
        embed = discord.Embed(title=self.title, color=discord.Color.blurple())
        for entry in page_items:
            name, value = _format_case(self.guild, entry)
            embed.add_field(name=name, value=value, inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{self.page_count} • {total} cases")
        return embed

    async def _turn(self, interaction, direction):
        if not _is_manager(interaction):
            await interaction.response.send_message(
                "You need Manage Server to browse modlogs.",
                ephemeral=True,
            )
            return
        try:
            self.page = max(0, min(self.page_count - 1, self.page + direction))
            self._refresh_buttons()
            await interaction.response.edit_message(
                embed=self.build_embed(), view=self
            )
        except Exception:
            print("[MODLOG] Pager turn failed:")
            traceback.print_exc()

    @discord.ui.button(label="Previous", emoji="\u25c0\ufe0f", style=discord.ButtonStyle.secondary)
    async def prev_button(self, button, interaction):
        await self._turn(interaction, -1)

    @discord.ui.button(label="Next", emoji="\u25b6\ufe0f", style=discord.ButtonStyle.secondary)
    async def next_button(self, button, interaction):
        await self._turn(interaction, +1)

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class CaseSelectView(discord.ui.View):
    """Pick one of a user's recent cases to view, edit or delete."""

    def __init__(self, guild, target_id, entries):
        super().__init__(timeout=300)
        self.guild = guild
        self.target_id = target_id
        self.entries = entries
        self.message = None
        options = []
        for entry in entries:
            case = entry["case"]
            ts = int(entry["ts"])
            label = f"#{entry['number']} {case.get('action', '?')} — <t:{ts}:D>"
            label = label[:100]
            reason = (case.get("reason") or "").strip()
            if len(reason) > 90:
                reason = reason[:87] + "..."
            options.append(discord.SelectOption(
                label=label,
                description=(f"{reason} (by {case.get('mod_name', '?')})"[:100]
                             if reason else f"by {case.get('mod_name', '?')}"),
                value=_case_key(entry),
            ))
        self.select = discord.ui.Select(
            placeholder="Pick a case to view…",
            options=options,
            min_values=1,
            max_values=1,
        )
        self.select.callback = self._on_select
        self.add_item(self.select)

    async def _on_select(self, interaction):
        if not _is_manager(interaction):
            await interaction.response.send_message(
                "You need Manage Server to edit mod cases.",
                ephemeral=True,
            )
            return
        try:
            key = _parse_case_key(interaction.data["values"][0])
            if key is None:
                await interaction.response.send_message(
                    "That selection could not be read. Run /modlogs_edit again.",
                    ephemeral=True,
                )
                return
            _data, _urec, _cases, _index, case = _resolve_case(
                self.guild.id, key
            )
            if case is None:
                await interaction.response.send_message(
                    "That case changed or was removed since the list was built. "
                    "Run /modlogs_edit again to pick it fresh.",
                    ephemeral=True,
                )
                return
            entry = {
                "user_id": key["user_id"],
                "index": _index,
                "case": case,
                "number": _case_number(_cases, _index),
                "ts": float(case.get("ts", 0) or 0),
            }
            name, value = _format_case(self.guild, entry)
            embed = discord.Embed(title="Mod case", color=discord.Color.blurple())
            embed.add_field(name=name, value=value, inline=False)
            detail = CaseDetailView(self.guild, key, entry)
            await interaction.response.edit_message(embed=embed, view=detail)
        except Exception:
            print("[MODLOG] Case select failed:")
            traceback.print_exc()
            try:
                await interaction.response.send_message(
                    "Something went wrong opening that case.",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class CaseDetailView(discord.ui.View):
    """Edit-reason / delete actions for one resolved case."""

    def __init__(self, guild, key, entry):
        super().__init__(timeout=300)
        self.guild = guild
        self.key = key
        self.entry = entry
        self.message = None

    @discord.ui.button(label="Edit reason", emoji="\u270f\ufe0f", style=discord.ButtonStyle.primary)
    async def edit_button(self, button, interaction):
        if not _is_manager(interaction):
            await interaction.response.send_message(
                "You need Manage Server to edit mod cases.",
                ephemeral=True,
            )
            return
        try:
            _data, _urec, _cases, _index, case = _resolve_case(
                self.guild.id, self.key
            )
            if case is None:
                await interaction.response.send_message(
                    "That case changed or was removed. "
                    "Run /modlogs_edit again to pick it fresh.",
                    ephemeral=True,
                )
                return
            await interaction.response.send_modal(
                EditReasonModal(self.guild, self.key, case)
            )
        except Exception:
            print("[MODLOG] Edit button failed:")
            traceback.print_exc()
            try:
                await interaction.response.send_message(
                    "Something went wrong opening the edit form.",
                    ephemeral=True,
                )
            except Exception:
                pass

    @discord.ui.button(label="Delete case", emoji="\U0001f5d1\ufe0f", style=discord.ButtonStyle.danger)
    async def delete_button(self, button, interaction):
        if not _is_manager(interaction):
            await interaction.response.send_message(
                "You need Manage Server to delete mod cases.",
                ephemeral=True,
            )
            return
        try:
            _data, _urec, _cases, _index, case = _resolve_case(
                self.guild.id, self.key
            )
            if case is None:
                await interaction.response.send_message(
                    "That case changed or was removed. "
                    "Run /modlogs_edit again to pick it fresh.",
                    ephemeral=True,
                )
                return
            entry = {
                "user_id": self.key["user_id"],
                "index": _index,
                "case": case,
                "number": _case_number(_cases, _index),
                "ts": float(case.get("ts", 0) or 0),
            }
            name, value = _format_case(self.guild, entry)
            embed = discord.Embed(
                title="Delete this case?",
                description="This cannot be undone.",
                color=discord.Color.red(),
            )
            embed.add_field(name=name, value=value, inline=False)
            confirm = DeleteConfirmView(self.guild, self.key, entry)
            await interaction.response.edit_message(embed=embed, view=confirm)
        except Exception:
            print("[MODLOG] Delete button failed:")
            traceback.print_exc()
            try:
                await interaction.response.send_message(
                    "Something went wrong opening the delete confirmation.",
                    ephemeral=True,
                )
            except Exception:
                pass

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


class EditReasonModal(discord.ui.Modal):
    """Change a case's reason (old reason prefilled)."""

    def __init__(self, guild, key, case):
        super().__init__(title="Edit case reason")
        self.guild = guild
        self.key = key
        self.old_reason = (case.get("reason") or "").strip()
        self.add_item(discord.ui.InputText(
            label="New reason",
            style=discord.InputTextStyle.paragraph,
            placeholder="Corrected reason",
            value=self.old_reason[:400],
            max_length=400,
        ))

    async def callback(self, interaction):
        new_reason = (self.children[0].value or "").strip() or "No reason given"
        try:
            ok, message, old = _apply_edit(self.guild.id, self.key, new_reason)
        except Exception:
            print("[MODLOG] Edit reason failed:")
            traceback.print_exc()
            await interaction.response.send_message(
                "Something went wrong saving that edit.",
                ephemeral=True,
            )
            return
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        member = self.guild.get_member(_safe_int(self.key["user_id"]))
        target = member.mention if member else f"<@{self.key['user_id']}>"
        await interaction.response.send_message(
            f"Case updated for {target}.\n"
            f"**Old reason:** {old.get('reason', '')}\n"
            f"**New reason:** {new_reason}",
            ephemeral=True,
        )
        await _log_mod_action(
            interaction.client, self.guild.id,
            "Mod case edited",
            f"**Target:** {target} (`{self.key['user_id']}`)\n"
            f"**Action:** {old.get('action', '?')}\n"
            f"**Old reason:** {old.get('reason', '')}\n"
            f"**New reason:** {new_reason}\n"
            f"**Edited by:** {interaction.user.mention}",
            discord.Color.orange(),
        )


class DeleteConfirmView(discord.ui.View):
    """Second step for deleting a case: the full case is on screen."""

    def __init__(self, guild, key, entry):
        super().__init__(timeout=300)
        self.guild = guild
        self.key = key
        self.entry = entry
        self.message = None

    @discord.ui.button(label="Yes, delete it", style=discord.ButtonStyle.danger)
    async def confirm_button(self, button, interaction):
        if not _is_manager(interaction):
            await interaction.response.send_message(
                "You need Manage Server to delete mod cases.",
                ephemeral=True,
            )
            return
        try:
            ok, message, old = _apply_delete(self.guild.id, self.key)
        except Exception:
            print("[MODLOG] Delete case failed:")
            traceback.print_exc()
            await interaction.response.send_message(
                "Something went wrong deleting that case.",
                ephemeral=True,
            )
            return
        for child in self.children:
            child.disabled = True
        if not ok:
            await interaction.response.send_message(message, ephemeral=True)
            return
        member = self.guild.get_member(_safe_int(self.key["user_id"]))
        target = member.mention if member else f"<@{self.key['user_id']}>"
        embed = discord.Embed(
            title="Case deleted",
            description=(
                f"**Target:** {target} (`{self.key['user_id']}`)\n"
                f"**Action:** {old.get('action', '?')}\n"
                f"**Reason was:** {old.get('reason', '')}"
            ),
            color=discord.Color.red(),
        )
        try:
            await interaction.response.edit_message(embed=embed, view=self)
        except Exception:
            await interaction.response.send_message(embed=embed, ephemeral=True)
        await _log_mod_action(
            interaction.client, self.guild.id,
            "Mod case deleted",
            f"**Target:** {target} (`{self.key['user_id']}`)\n"
            f"**Action:** {old.get('action', '?')}\n"
            f"**Reason was:** {old.get('reason', '')}\n"
            f"**Deleted by:** {interaction.user.mention}",
            discord.Color.red(),
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel_button(self, button, interaction):
        for child in self.children:
            child.disabled = True
        try:
            await interaction.response.edit_message(
                content="Delete cancelled — the case was not changed.",
                embed=None, view=self,
            )
        except Exception:
            await interaction.response.send_message(
                "Delete cancelled — the case was not changed.",
                ephemeral=True,
            )

    async def on_timeout(self):
        for child in self.children:
            child.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except Exception:
                pass


# ---------- cog ----------

class Modlogs(commands.Cog):
    """Paginated mod-case viewer, recap, edit/delete, and by-moderator view."""

    def __init__(self, bot):
        self.bot = bot

    # ---------- shared helpers ----------

    def _resolve_target(self, ctx, member, user_id):
        """member wins; else a raw user id; else (None, None, error)."""
        if member is not None:
            return member.id, member, None
        if user_id:
            parsed = _safe_int(user_id.strip())
            if parsed is None:
                return None, None, "That user ID does not look like a number."
            return parsed, ctx.guild.get_member(parsed), None
        return None, None, "Pick a member or give a user ID."

    async def _send_pager(self, ctx, title, items):
        view = ModlogPagerView(ctx.guild, items, title)
        message = await ctx.followup.send(
            embed=view.build_embed(), view=view, ephemeral=True, wait=True
        )
        view.message = message

    # ---------- /modlogs ----------

    @discord.slash_command(
        name="modlogs",
        description="Browse moderation cases, newest first (filter by user, type, or date).",
        guild_ids=GUILD_IDS,
    )
    async def modlogs(
        self,
        ctx,
        member: discord.Option(
            discord.Member,
            "Only show cases for this member",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "Or a raw user ID (used when the member has left the server)",
            required=False,
            default=None,
        ),
        type_filter: discord.Option(
            str,
            "Only show cases of this type",
            name="type",
            required=False,
            default=None,
            choices=TYPE_CHOICES,
        ),
        before: discord.Option(
            str,
            "Only cases before this date (YYYY-MM-DD)",
            required=False,
            default=None,
        ),
        after: discord.Option(
            str,
            "Only cases from this date onwards (YYYY-MM-DD)",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "modlogs", _default_manage_or_admin):
            return
        target_id = None
        if member is not None:
            target_id = member.id
        elif user_id:
            target_id = _safe_int(user_id.strip())
            if target_id is None:
                await ctx.respond(
                    "That user ID does not look like a number.",
                    ephemeral=True,
                )
                return
        before_ts = after_ts = None
        if before:
            before_ts, err = _parse_date(before)
            if err:
                await ctx.respond(err, ephemeral=True)
                return
        if after:
            after_ts, err = _parse_date(after)
            if err:
                await ctx.respond(err, ephemeral=True)
                return
        if before_ts is not None and after_ts is not None and after_ts >= before_ts:
            await ctx.respond(
                "The 'after' date has to be before the 'before' date.",
                ephemeral=True,
            )
            return
        await ctx.defer(ephemeral=True)
        try:
            items = _collect_cases(
                ctx.guild.id,
                target_id=target_id,
                type_filter=type_filter,
                before_ts=before_ts,
                after_ts=after_ts,
            )
        except Exception:
            print("[MODLOG] /modlogs collect failed:")
            traceback.print_exc()
            await ctx.followup.send(
                "Could not read the modlog.",
                ephemeral=True,
            )
            return
        total = len(items)
        if total > GUILD_SCAN_CAP:
            items = items[:GUILD_SCAN_CAP]
        if target_id is not None:
            target_member = ctx.guild.get_member(target_id)
            title = (f"Mod cases — {target_member.display_name}"
                     if target_member else f"Mod cases — <@{target_id}>")
        else:
            title = "Mod cases — most recent"
        if total > GUILD_SCAN_CAP:
            title += f" (showing the {GUILD_SCAN_CAP} most recent of {total})"
        await self._send_pager(ctx, title, items)

    # ---------- /modlogs_recap ----------

    @discord.slash_command(
        name="modlogs_recap",
        description="Counts by action type, most recent case, and tempban status for one user.",
        guild_ids=GUILD_IDS,
    )
    async def modlogs_recap(
        self,
        ctx,
        member: discord.Option(
            discord.Member,
            "The member to recap",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "Or a raw user ID (used when the member has left the server)",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "modlogs_recap", _default_manage_or_admin):
            return
        target_id, target_member, err = self._resolve_target(ctx, member, user_id)
        if err:
            await ctx.respond(err, ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            grec = _load_guild(ctx.guild.id)
            urec = grec.get(str(target_id), {})
            if not isinstance(urec, dict):
                urec = {}
            cases = urec.get("cases", [])
            if not isinstance(cases, list):
                cases = []
            items = _collect_cases(ctx.guild.id, target_id=target_id)
            tempbans = grec.get("tempbans", {})
            tb = tempbans.get(str(target_id)) if isinstance(tempbans, dict) else None
        except Exception:
            print("[MODLOG] /modlogs_recap failed:")
            traceback.print_exc()
            await ctx.followup.send(
                "Could not read the modlog.",
                ephemeral=True,
            )
            return
        display = (target_member.display_name if target_member
                   else f"<@{target_id}>")
        embed = discord.Embed(
            title=f"Mod recap — {display}",
            color=discord.Color.blurple(),
        )
        counts = {}
        for item in items:
            base = _action_base(item["case"].get("action"))
            counts[base] = counts.get(base, 0) + 1
        if counts:
            lines = [f"{name.title()}: {n}"
                     for name, n in sorted(counts.items(), key=lambda kv: -kv[1])]
            embed.add_field(name=f"Cases ({len(items)})",
                            value="\n".join(lines), inline=True)
        else:
            embed.add_field(name="Cases (0)", value="No recorded actions.",
                            inline=True)
        embed.add_field(name="Warns", value=str(len(urec.get("warns", []) or [])),
                        inline=True)
        embed.add_field(name="Notes", value=str(len(urec.get("notes", []) or [])),
                        inline=True)
        if items:
            name, value = _format_case(ctx.guild, items[0])
            embed.add_field(name="Most recent", value=f"**{name}**\n{value}",
                            inline=False)
        if isinstance(tb, dict) and tb.get("unban_at"):
            try:
                unban_at = int(float(tb["unban_at"]))
            except (TypeError, ValueError):
                unban_at = 0
            import time as _time
            if unban_at and unban_at > _time.time():
                embed.add_field(
                    name="Active tempban",
                    value=(f"Until <t:{unban_at}:F> (<t:{unban_at}:R>)\n"
                           f"**Reason:** {tb.get('reason', '')}\n"
                           f"**By:** {tb.get('mod_name', '?')}"),
                    inline=False,
                )
            elif unban_at:
                embed.add_field(
                    name="Tempban",
                    value="Expired — waiting for the sweep to lift it.",
                    inline=False,
                )
            else:
                embed.add_field(name="Tempban", value="No active tempban.",
                                inline=False)
        else:
            embed.add_field(name="Tempban", value="No active tempban.",
                            inline=False)
        await ctx.followup.send(embed=embed, ephemeral=True)

    # ---------- /modlogs_edit ----------

    @discord.slash_command(
        name="modlogs_edit",
        description="Pick one of a user's recent cases to edit its reason or delete it.",
        guild_ids=GUILD_IDS,
    )
    async def modlogs_edit(
        self,
        ctx,
        member: discord.Option(
            discord.Member,
            "The member whose case to change",
            required=False,
            default=None,
        ),
        user_id: discord.Option(
            str,
            "Or a raw user ID (used when the member has left the server)",
            required=False,
            default=None,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "modlogs_edit", _default_manage_or_admin):
            return
        target_id, target_member, err = self._resolve_target(ctx, member, user_id)
        if err:
            await ctx.respond(err, ephemeral=True)
            return
        await ctx.defer(ephemeral=True)
        try:
            items = _collect_cases(ctx.guild.id, target_id=target_id)
        except Exception:
            print("[MODLOG] /modlogs_edit collect failed:")
            traceback.print_exc()
            await ctx.followup.send(
                "Could not read the modlog.",
                ephemeral=True,
            )
            return
        if not items:
            display = (target_member.mention if target_member
                       else f"<@{target_id}>")
            await ctx.followup.send(
                f"No cases found for {display}.",
                ephemeral=True,
            )
            return
        entries = items[:SELECT_LIMIT]
        display = (target_member.display_name if target_member
                   else f"<@{target_id}>")
        embed = discord.Embed(
            title=f"Edit a case — {display}",
            description=(f"Pick one of their {len(entries)} most recent cases "
                         f"({len(items)} total)."),
            color=discord.Color.blurple(),
        )
        view = CaseSelectView(ctx.guild, target_id, entries)
        message = await ctx.followup.send(embed=embed, view=view,
                                          ephemeral=True, wait=True)
        view.message = message

    # ---------- /mod_actions ----------

    @discord.slash_command(
        name="mod_actions",
        description="Every moderation action performed by one moderator.",
        guild_ids=GUILD_IDS,
    )
    async def mod_actions(
        self,
        ctx,
        moderator: discord.Option(
            discord.Member,
            "The moderator whose actions to list",
            required=True,
        ),
    ):
        from utils.permissions import check_slash_permission, _default_manage_or_admin
        if not await check_slash_permission(ctx, "mod_actions", _default_manage_or_admin):
            return
        await ctx.defer(ephemeral=True)
        try:
            items = _collect_cases(
                ctx.guild.id,
                moderator_id=moderator.id,
                moderator_name=str(moderator),
            )
        except Exception:
            print("[MODLOG] /mod_actions collect failed:")
            traceback.print_exc()
            await ctx.followup.send(
                "Could not read the modlog.",
                ephemeral=True,
            )
            return
        await self._send_pager(ctx, f"Actions by {moderator.display_name}", items)


def setup(bot):
    bot.add_cog(Modlogs(bot))
