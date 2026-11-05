# cogs/ServerSettings.py
"""One command that shows every system's on/off state and key config.

/bot_settings gathers the live config for each bot system (levels,
voice XP, automod, logger, lockdown, watchlist, tickets, QOTD, debug,
introductions, appeals, ban-log, timeout board, badges) and presents
it as a set of embeds, one per message (Discord caps the total
characters across all embeds in one message at 6000). Each section
reads its own store and is wrapped so one unreadable system shows as
"couldn't read" instead of breaking the whole overview.

The custom permissions system is intentionally left out -- it has its
own /perm_overview and /perm_commands.
"""
import asyncio
import os
import time
from pathlib import Path

import discord
from discord.ext import commands

from config import GUILD_IDS
from data.DB.Storage.storage import (
    get_levels,
    get_voice_xp_config,
    get_automod_config,
    get_qotd_config,
    get_ticket_guild_config,
    get_ticket_config,
    get_active_tickets,
    get_appeal_guild_config,
    get_ghlog_settings,
    get_introduction_config,
    get_timeout_board_config,
    list_custom_badges,
)
from data.DB.db import database
from data.DB.models import lockdown_channels


def _on_off(value):
    return "ON" if value else "OFF"


def _chan(guild, channel_id):
    """Channel mention, or 'not set' when unset/gone."""
    if not channel_id:
        return "not set"
    try:
        channel = guild.get_channel(int(channel_id))
    except (ValueError, TypeError):
        channel = None
    return channel.mention if channel else "not set"


def _role(guild, role_id):
    """Role mention, or 'not set' when unset/gone."""
    if not role_id:
        return "not set"
    try:
        role = guild.get_role(int(role_id))
    except (ValueError, TypeError):
        role = None
    return role.mention if role else "not set"


def _chunk_embeds(title, color, fields, footer=None):
    """Pack (name, value) fields into embeds, splitting on LINE
    boundaries, never mid-line (a hard 1024-char cut can split a
    `code` span or a <@&id> mention in half, and an unmatched backtick
    makes Discord render the rest of the chunk as code). Each embed
    stays under 25 fields and 5900 chars total."""
    embeds = []
    cur = discord.Embed(title=title, color=color)
    cur_len = len(title)
    if footer:
        cur.set_footer(text=footer)
        cur_len += len(footer)
    for name, value in fields:
        lines = value.split("\n")
        chunks = []
        cur_chunk = ""
        for line in lines:
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


# ----- one gatherer per system; each returns (field name, field value).
# Every gatherer is defensive: any read failure yields a short
# "couldn't read" line instead of breaking the overview.


async def _section_levels(guild):
    try:
        db = await get_levels(str(guild.id))
    except Exception:
        return ("Levels & XP", "Couldn't read settings.")
    s = db.get("settings", {}) if isinstance(db, dict) else {}
    event = ""
    until = s.get("xp_event_until", 0) or 0
    if until and until > time.time():
        event = " — XP event %sx running" % s.get("xp_event_multiplier", 2)
    lines = [
        "Status: **%s**" % _on_off(s.get("levels_enabled", False)),
        "XP: %s–%s/msg, cooldown %ss" % (
            s.get("xp_min", 1), s.get("xp_max", 5), s.get("cooldown", 0)),
        "Level channel: %s" % _chan(guild, s.get("levelup_channel_id")),
        "Game XP: %s | No-XP channels: %d | Level roles: %d%s" % (
            _on_off(s.get("game_xp", True)),
            len(s.get("no_xp_channels", []) or []),
            len(s.get("level_roles", {}) or {}),
            event),
        "Level-up message: %s" % (
            "Custom" if s.get("levelup_message") else "Default"),
    ]
    return ("Levels & XP", "\n".join(lines))


async def _section_voice_xp(guild):
    try:
        cfg = await get_voice_xp_config(str(guild.id))
    except Exception:
        return ("Voice XP", "Couldn't read settings.")
    cfg = cfg or {}
    lines = [
        "Status: **%s**" % _on_off(cfg.get("enabled", True)),
        "XP: %s/min, daily cap %s XP" % (
            cfg.get("xp_per_minute", 1), cfg.get("daily_cap_xp", 100)),
    ]
    return ("Voice XP", "\n".join(lines))


async def _section_automod(guild):
    try:
        cfg = await get_automod_config(str(guild.id))
    except Exception:
        return ("Automod", "Couldn't read settings.")
    cfg = cfg or {}
    on = [label for key, label in (
        ("spam_enabled", "spam"),
        ("invites_enabled", "invites"),
        ("external_links_enabled", "external links"),
        ("caps_enabled", "caps"),
    ) if cfg.get(key)]
    lines = [
        "Filters on: %s" % (", ".join(on) if on else "none"),
        "Spam: %s in %ss" % (
            cfg.get("spam_threshold", 5), cfg.get("spam_window_seconds", 10)),
    ]
    return ("Automod", "\n".join(lines))


def _logger_section_sync(guild_id):
    """Sync read of the Logger's own SQLite DB (run in a thread)."""
    try:
        from cogs.Logger.database import db as logger_db
        from cogs.Logger.config import ALL_EVENTS
    except Exception:
        return ("Logger", "Couldn't read settings.")
    try:
        channels = logger_db.get_all_log_channels(str(guild_id))
        enabled = sum(
            1 for key in ALL_EVENTS
            if logger_db.is_enabled(str(guild_id), key))
    except Exception:
        return ("Logger", "Couldn't read settings.")
    if channels:
        chan_text = ", ".join(
            "%s: %s" % (log_type, "<#%s>" % cid)
            for log_type, cid in sorted(channels.items()))
    else:
        chan_text = "no log channels set"
    lines = [
        "Log channels: %s" % chan_text,
        "Events: %d of %d on" % (enabled, len(ALL_EVENTS)),
    ]
    return ("Logger", "\n".join(lines))


async def _section_logger(guild):
    return await asyncio.to_thread(_logger_section_sync, guild.id)


async def _section_lockdown(guild):
    try:
        rows = await database.fetch_all(
            lockdown_channels.select().where(
                lockdown_channels.c.guild_id == str(guild.id)))
    except Exception:
        return ("Lockdown", "Couldn't read settings.")
    if not rows:
        return ("Lockdown", "No channels locked.")
    mentions = []
    for row in rows:
        cid = row["channel_id"]
        mentions.append(_chan(guild, cid))
    return ("Lockdown", "Locked (%d): %s" % (len(rows), ", ".join(mentions)))


def _watchlist_section_sync(guild_id):
    """Sync read of the watchlist store (run in a thread)."""
    try:
        from config import load_json
        data = load_json("watchlist_data.json") or {}
    except Exception:
        return ("WatchList", "Couldn't read settings.")
    try:
        gdata = data.get(str(guild_id), {}) or {}
        users = gdata.get("users", {}) or {}
        channel = gdata.get("log_channel_id")
    except Exception:
        return ("WatchList", "Couldn't read settings.")
    lines = [
        "Watched users: %d" % len(users),
        "Log channel: %s" % ("<#%s>" % channel if channel else "not set"),
    ]
    return ("WatchList", "\n".join(lines))


async def _section_watchlist(guild):
    return await asyncio.to_thread(_watchlist_section_sync, guild.id)


async def _section_tickets(guild):
    try:
        gcfg = await get_ticket_guild_config(str(guild.id))
        cfg = await get_ticket_config(str(guild.id))
        active = await get_active_tickets(str(guild.id))
    except Exception:
        return ("Tickets", "Couldn't read settings.")
    gcfg = gcfg or {}
    cfg = cfg or {}
    active = active or {}
    lines = [
        "Status: **%s**" % _on_off(gcfg.get("enabled", True)),
        "Panel channel: %s" % _chan(guild, cfg.get("panel_channel_id")),
        "Open tickets: %d (next #%d)" % (
            len(active), gcfg.get("next_number", 1)),
    ]
    return ("Tickets", "\n".join(lines))


async def _section_qotd(guild):
    try:
        cfg = await get_qotd_config(str(guild.id))
    except Exception:
        return ("QOTD", "Couldn't read settings.")
    cfg = cfg or {}
    lines = [
        "Status: **%s**" % _on_off(cfg.get("enabled", True)),
        "Channel: %s" % _chan(guild, cfg.get("channel_id")),
    ]
    return ("QOTD", "\n".join(lines))


def _debug_section_sync():
    """Sync read of the debug flag (run in a thread)."""
    try:
        from cogs.DebugCog import _debug_enabled
        return ("Debug", "Status: **%s**" % _on_off(_debug_enabled()))
    except Exception:
        pass
    # Fall back to the flag file + env var directly.
    try:
        flag = Path(__file__).resolve().parent.parent / "data" / ".debug_enabled"
        if flag.exists():
            on = flag.read_text().strip().lower() in ("1", "true", "yes", "on")
        else:
            on = os.environ.get("DEBUG", "").lower() in ("1", "true", "yes", "on")
        return ("Debug", "Status: **%s**" % _on_off(on))
    except Exception:
        return ("Debug", "Couldn't read settings.")


async def _section_debug(guild):
    return await asyncio.to_thread(_debug_section_sync)


async def _section_intro(guild):
    try:
        cfg = await get_introduction_config(str(guild.id))
    except Exception:
        return ("Introductions", "Couldn't read settings.")
    cfg = cfg or {}
    lines = [
        "Intro channel: %s" % _chan(guild, cfg.get("channel_id")),
        "Intro role: %s" % _role(guild, cfg.get("role_id")),
        "Log channel: %s" % _chan(guild, cfg.get("log_channel_id")),
        "Auto-assign role: %s | Scan on message: %s" % (
            _on_off(cfg.get("auto_assign_role", True)),
            _on_off(cfg.get("scan_on_message", True))),
    ]
    return ("Introductions", "\n".join(lines))


async def _section_appeals(guild):
    try:
        cfg = await get_appeal_guild_config(str(guild.id))
    except Exception:
        return ("Appeals", "Couldn't read settings.")
    cfg = cfg or {}
    return ("Appeals", "Status: **%s**" % _on_off(cfg.get("enabled", True)))


async def _section_ghlog(guild):
    try:
        cfg = await get_ghlog_settings(str(guild.id))
    except Exception:
        return ("Ban log", "Couldn't read settings.")
    cfg = cfg or {}
    return ("Ban log",
            "Evidence channel: %s" % _chan(guild, cfg.get("evidence_channel_id")))


async def _section_timeout_board(guild):
    try:
        cfg = await get_timeout_board_config(str(guild.id))
    except Exception:
        return ("Timeout board", "Couldn't read settings.")
    cfg = cfg or {}
    return ("Timeout board",
            "Board channel: %s" % _chan(guild, cfg.get("channel_id")))


async def _section_badges(guild):
    try:
        badges = await list_custom_badges(str(guild.id))
    except Exception:
        return ("Badges", "Couldn't read settings.")
    badges = badges or []
    if not badges:
        return ("Badges", "No custom badges.")
    names = ", ".join("`%s`" % (b.get("name") or b.get("slug") or "?")
                      for b in badges[:10])
    more = " (+%d more)" % (len(badges) - 10) if len(badges) > 10 else ""
    return ("Badges", "Custom badges (%d): %s%s" % (len(badges), names, more))


_SECTIONS = (
    _section_levels,
    _section_voice_xp,
    _section_automod,
    _section_logger,
    _section_lockdown,
    _section_watchlist,
    _section_tickets,
    _section_qotd,
    _section_debug,
    _section_intro,
    _section_appeals,
    _section_ghlog,
    _section_timeout_board,
    _section_badges,
)


class ServerSettings(commands.Cog):
    """Overview of every bot system's config for this server."""

    def __init__(self, bot):
        self.bot = bot

    @commands.slash_command(name="bot_settings", description="Show every bot system's on/off state and config", guild_ids=GUILD_IDS)
    async def show_bot_settings(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "bot_settings", _default_admin_only):
            return
        if interaction.guild is None:
            await interaction.respond("Use this command in a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        results = await asyncio.gather(
            *(_fn(guild) for _fn in _SECTIONS), return_exceptions=True)
        fields = []
        for fn, result in zip(_SECTIONS, results):
            if isinstance(result, Exception):
                fields.append((fn.__name__.replace("_section_", "").replace("_", " ").title(),
                               "Couldn't read settings."))
            else:
                fields.append(result)
        embeds = _chunk_embeds(
            "Bot settings for %s" % guild.name,
            discord.Color.blurple(),
            fields,
            footer="Custom permissions are not shown here -- see /perm_overview.",
        )
        # Discord caps the TOTAL characters across all embeds in one
        # message at 6000, so send one embed per message.
        await interaction.followup.send(embed=embeds[0], ephemeral=True)
        for extra in embeds[1:]:
            await interaction.followup.send(embed=extra, ephemeral=True)


def setup(client):
    client.add_cog(ServerSettings(client))
