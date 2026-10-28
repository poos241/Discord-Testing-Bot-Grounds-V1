# cogs/Automod.py
"""Automod basics (built 2026-10-28).

Four small, per-guild, opt-in rules. Every rule defaults to OFF, so a
server that never touches /automod or the web Logger settings page
gets no filtering at all. Toggles live in the automod_config table
(data/DB/models.py) and are shared by the /automod slash commands and
the Automod card on the web Logger settings page, so the two UIs can
never disagree.

Rules (checked in this order; the first match wins and the message
is deleted once, not once per rule):

  - spam: more than spam_threshold messages from one member inside
    spam_window_seconds (defaults: 5 messages in 10 seconds).
    Message timestamps live only in memory, so a bot restart clears
    the burst history -- same trade-off as VoiceXP's unbanked minutes.
  - invites: a discord.gg / discord.com/invite / discordapp.com/invite
    link. The guild's own vanity code (if it has one) is allowed, so
    the server's own invite is not eaten; every other invite is.
  - external links: any http(s) URL whose host is not a Discord host
    (discord.com, discord.gg, discordapp.com, including subdomains).
    Invite links are caught by the invites rule first, so with only
    this rule on, a discord.gg link still passes.
  - caps: at least 10 letters, at least 80% of them uppercase.

Members with Manage Messages (mods and admins) are exempt from all
four rules, and bots are never filtered. The action is always the
same: delete the message (best effort -- a failed delete is still
logged, with the failure noted) and post an embed to the Logger's
moderation channel via ModerationLogger.send, which also records the
action in the Logger's web event history. Deleting a message also
trips the Logger's own "Message Deleted" entry, so the original
content stays visible in the log channel alongside the automod
embed. There is no DM warning and no timeout/ban in this version --
deliberately small, per the queue spec.

Per-user log cooldown: a member tripping the same rule repeatedly
gets one log embed per 60 seconds; the messages are still deleted,
the log channel just does not get spammed with one embed each.

Tables: automod_config in data/DB/models.py. Storage helpers live in
data/DB/Storage/storage.py. New table only -- create_all() creates
it on the next bot boot and never alters an existing table.
"""
import re
import time
from collections import deque

import discord
from discord.ext import commands
from discord.commands import SlashCommandGroup

from config import GUILD_IDS, Manage_messages_required, extra_help
from data.DB.db import database
from data.DB.Storage.storage import (
    get_automod_config,
    save_automod_config,
)

# Spam defaults (also the row defaults in get_automod_config).
SPAM_DEFAULT_THRESHOLD = 5
SPAM_DEFAULT_WINDOW = 10
# Caps rule: fixed thresholds, not DB settings -- keep the rule count
# small and the tuning surface to the spam rule, which is the one
# that actually needs per-server tuning.
CAPS_MIN_LETTERS = 10
CAPS_MIN_UPPER_RATIO = 0.80
# One log embed per member per rule per this many seconds; deletes
# still happen on every offending message.
LOG_COOLDOWN_SECONDS = 60
# Rule keys, in the order they are checked. The toggle command and
# the web page both use these exact strings.
RULES = ("spam", "invites", "external_links", "caps")

_INVITE_RE = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"(?:discord\.gg|discord\.com/invite|discordapp\.com/invite)"
    r"/([A-Za-z0-9-]+)",
    re.IGNORECASE,
)
_URL_RE = re.compile(r"https?://([A-Za-z0-9.\-]+)", re.IGNORECASE)
_DISCORD_HOSTS = ("discord.com", "discord.gg", "discordapp.com")


def _is_discord_host(host):
    host = host.lower().rstrip(".")
    return any(host == h or host.endswith("." + h) for h in _DISCORD_HOSTS)


def _caps_hit(content):
    letters = [c for c in content if c.isalpha()]
    if len(letters) < CAPS_MIN_LETTERS:
        return False
    upper = sum(1 for c in letters if c.isupper())
    return upper / len(letters) >= CAPS_MIN_UPPER_RATIO


class Automod(commands.Cog):
    """Small configurable message filter: spam, invites, links, caps."""

    automod = SlashCommandGroup("automod", "Automod filter controls",
                                guild_ids=GUILD_IDS)

    def __init__(self, bot):
        self.bot = bot
        # (guild_id, user_id) -> deque of message timestamps (floats).
        self._recent = {}
        # (guild_id, user_id, rule) -> last log-embed timestamp.
        self._last_logged = {}

    # ---------- internals ----------

    async def _ensure_db(self):
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[Automod] DB connect check failed: {e!r}")

    def _rule_hit(self, message, cfg):
        """First matching rule for this message, or None.

        Spam history is updated here on every message (before the
        rule checks), so a burst counts messages even when another
        rule deletes one of them first.
        """
        content = message.content or ""
        now = time.time()
        key = (str(message.guild.id), str(message.author.id))
        window = int(cfg.get("spam_window_seconds", SPAM_DEFAULT_WINDOW)) or SPAM_DEFAULT_WINDOW
        history = self._recent.setdefault(key, deque())
        history.append(now)
        while history and now - history[0] > window:
            history.popleft()

        if cfg.get("invites_enabled"):
            match = _INVITE_RE.search(content)
            if match:
                # The guild's own vanity invite is allowed; anything
                # else that looks like an invite is not.
                vanity = getattr(message.guild, "vanity_url_code", None)
                if not vanity or match.group(1).lower() != vanity.lower():
                    return "invites"
        if cfg.get("external_links_enabled"):
            match = _URL_RE.search(content)
            if match and not _is_discord_host(match.group(1)):
                return "external_links"
        if cfg.get("caps_enabled") and _caps_hit(content):
            return "caps"
        if cfg.get("spam_enabled"):
            threshold = int(cfg.get("spam_threshold", SPAM_DEFAULT_THRESHOLD)) or SPAM_DEFAULT_THRESHOLD
            if len(history) >= threshold:
                return "spam"
        return None

    async def _act(self, message, rule):
        """Delete the message and log it to the Logger. Returns True
        when the delete itself succeeded."""
        deleted = True
        try:
            await message.delete(reason=f"Automod: {rule}")
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            deleted = False
        # One embed per member per rule per minute; deletes continue
        # even inside the cooldown, only the log embed is throttled.
        now = time.time()
        log_key = (str(message.guild.id), str(message.author.id), rule)
        if now - self._last_logged.get(log_key, 0) < LOG_COOLDOWN_SECONDS:
            return deleted
        self._last_logged[log_key] = now
        await self._log(message, rule, deleted)
        return deleted

    async def _log(self, message, rule, deleted):
        """Best-effort post to the Logger's moderation channel."""
        try:
            logger_cog = self.bot.get_cog("ModerationLogger")
            if logger_cog is None:
                return
            embed = discord.Embed(
                title=f"Automod: {rule.replace('_', ' ').title()}",
                color=discord.Color.orange(),
                timestamp=discord.utils.utcnow())
            embed.add_field(name="User",
                            value=f"{message.author} (`{message.author.id}`)",
                            inline=True)
            embed.add_field(name="Channel", value=message.channel.mention,
                            inline=True)
            embed.add_field(name="Rule", value=rule, inline=True)
            content = (message.content or "*No text content.*")[:500]
            embed.add_field(name="Content", value=content, inline=False)
            embed.add_field(
                name="Action",
                value=("Message deleted." if deleted
                       else "Delete failed -- the bot may be missing "
                            "Manage Messages in that channel."),
                inline=False)
            embed.set_footer(text="Kush Bush Logger")
            await logger_cog.send(message.guild, "moderation", embed)
        except Exception:
            pass

    # ---------- message filter ----------

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.guild is None:
            return
        # Mods (Manage Messages, which includes admins) are exempt.
        try:
            if message.author.guild_permissions.manage_messages:
                return
        except AttributeError:
            return
        await self._ensure_db()
        try:
            cfg = await get_automod_config(str(message.guild.id))
        except Exception as e:
            print(f"[Automod] Config read failed: {e!r}")
            return
        if not any(cfg.get(f"{rule}_enabled") for rule in RULES):
            return
        rule = self._rule_hit(message, cfg)
        if rule is not None:
            await self._act(message, rule)

    # ---------- commands ----------

    @automod.command(name="status", description="Show the automod rules and spam settings for this server.")
    @extra_help("Lists all four automod rules with on/off state, plus the spam burst threshold and window. Read-only; mods use /automod toggle and /automod config to change things.")
    @Manage_messages_required()
    async def automod_status(self, ctx):
        if ctx.guild is None:
            return await ctx.respond("Automod commands only work in a server.",
                                     ephemeral=True)
        await self._ensure_db()
        cfg = await get_automod_config(str(ctx.guild.id))
        lines = [
            f"Spam bursts: **{'on' if cfg.get('spam_enabled') else 'off'}** "
            f"({cfg.get('spam_threshold')} messages in "
            f"{cfg.get('spam_window_seconds')}s)",
            f"Invite links: **{'on' if cfg.get('invites_enabled') else 'off'}**",
            f"External links: **{'on' if cfg.get('external_links_enabled') else 'off'}**",
            f"All-caps: **{'on' if cfg.get('caps_enabled') else 'off'}** "
            f"({CAPS_MIN_LETTERS}+ letters, "
            f"{int(CAPS_MIN_UPPER_RATIO * 100)}%+ uppercase)",
        ]
        embed = discord.Embed(
            title="Automod Settings", color=discord.Color.orange(),
            description="\n".join(lines))
        embed.set_footer(text="Change these with /automod toggle and /automod config, or on the web Logger settings page.")
        await ctx.respond(embed=embed, ephemeral=True)

    @automod.command(name="toggle", description="Turn one automod rule on or off (leave enabled blank to flip it).")
    @extra_help("Rule names: spam, invites, external_links, caps. With no enabled value the rule flips to its opposite state. Changes apply immediately and are also reflected on the web Logger settings page, since both read the same automod_config row.")
    @Manage_messages_required()
    async def automod_toggle(self, ctx,
                             rule: discord.Option(str, "Rule to change: spam, invites, external_links, or caps"),
                             enabled: discord.Option(bool, "True = on, False = off (blank flips the current state)", required=False, default=None)):
        if ctx.guild is None:
            return await ctx.respond("Automod commands only work in a server.",
                                     ephemeral=True)
        rule = (rule or "").strip().lower()
        if rule not in RULES:
            return await ctx.respond(
                "Unknown rule. Use one of: spam, invites, external_links, caps.",
                ephemeral=True)
        await self._ensure_db()
        cfg = await get_automod_config(str(ctx.guild.id))
        key = f"{rule}_enabled"
        new_value = (not cfg.get(key)) if enabled is None else bool(enabled)
        await save_automod_config(str(ctx.guild.id), {key: new_value})
        await ctx.respond(
            f"Automod rule **{rule}** is now **{'on' if new_value else 'off'}**.",
            ephemeral=True)

    @automod.command(name="config", description="Set the spam burst threshold and window.")
    @extra_help("Threshold: how many messages from one member inside the window trips the spam rule (1-50). Window: the window in seconds (5-300). Other rules have no numeric settings: caps is fixed at 10+ letters and 80%+ uppercase.")
    @Manage_messages_required()
    async def automod_config_cmd(self, ctx,
                                 threshold: discord.Option(int, "Messages from one member that trip the spam rule (1-50)", required=False, default=None),
                                 window: discord.Option(int, "Window in seconds the messages must fall inside (5-300)", required=False, default=None)):
        if ctx.guild is None:
            return await ctx.respond("Automod commands only work in a server.",
                                     ephemeral=True)
        if threshold is None and window is None:
            return await ctx.respond(
                "Give a threshold, a window, or both. Current values are in /automod status.",
                ephemeral=True)
        if threshold is not None and not 1 <= threshold <= 50:
            return await ctx.respond("Threshold must be between 1 and 50.",
                                     ephemeral=True)
        if window is not None and not 5 <= window <= 300:
            return await ctx.respond("Window must be between 5 and 300 seconds.",
                                     ephemeral=True)
        await self._ensure_db()
        payload = {}
        if threshold is not None:
            payload["spam_threshold"] = int(threshold)
        if window is not None:
            payload["spam_window_seconds"] = int(window)
        await save_automod_config(str(ctx.guild.id), payload)
        cfg = await get_automod_config(str(ctx.guild.id))
        await ctx.respond(
            f"Spam rule is now **{cfg.get('spam_threshold')} messages in "
            f"{cfg.get('spam_window_seconds')}s**.",
            ephemeral=True)


def setup(bot):
    bot.add_cog(Automod(bot))
