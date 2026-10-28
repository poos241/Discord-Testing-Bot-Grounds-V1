# cogs/CustomBadges.py
""" Mod-awardable custom badges (built 2026-10-28).

Mods create badge definitions for their server and award them to
members; awarded badges show on the member's profile badge shelf
next to the hard-coded earned badges (Level 5/10/25/50, First Game,
etc.). Badge definitions and awards live in two new tables
(custom_badges, custom_badge_awards) in data/DB/models.py; the web
profile APIs append them via get_custom_badges() in
web/blueprints/profiles.py, so no template change was needed for
the shelf itself.

Commands (guild-scoped, all gated on Manage Messages -- the same
mod gate Automod uses):

  - /badge create <name> [icon] [description] -- create a badge
    for this server. The name becomes a URL-safe slug (lowercase,
    spaces/punctuation become hyphens); the slug is unique per
    server, so creating "MVP" twice is rejected. Icon defaults
    to a medal. Note: Unicode emoji render on the web profile
    shelf; a Discord custom emoji (e.g. <:name:id>) shows as raw
    text there.
  - /badge award <badge> <member> -- award a badge. The badge
    option autocompletes this server's badges (name + slug shown,
    slug submitted); typing a name or slug by hand works too.
  - /badge remove <badge> <member> -- revoke one member's award.
  - /badge delete <badge> -- delete the badge definition and all
    of its awards (the reply says how many awards were removed).
  - /badge list -- list this server's badges with award counts.

Privacy: awards never carry guild info onto the web. The profile
APIs return only icon/name/description for custom badges, so a
public profile shows the badge but never reveals which server it
came from -- the same strip rule as roles and local info.

What is deliberately left out: custom badges cannot be picked as
the profile's featured badge (the edit page only accepts the
hard-coded BADGE_DEFS keys); no award expiry, no per-badge
permissions beyond the mod gate, and no DM to the recipient --
the award appears in their profile activity feed instead.
"""
import re

import discord
from discord.commands import SlashCommandGroup
from discord.ext import commands

from config import GUILD_IDS, Manage_messages_required, extra_help
from data.DB.db import database
from data.DB.Storage.storage import (
    award_custom_badge,
    count_custom_badge_awards,
    create_custom_badge,
    delete_custom_badge,
    get_custom_badge,
    get_custom_badge_by_name,
    list_custom_badges,
    log_activity,
    remove_custom_badge_award,
)

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_MAX_NAME_LEN = 64
_MAX_DESC_LEN = 200
_MAX_ICON_LEN = 64


def _slugify(name):
    """'Community MVP!' -> 'community-mvp' (max 32 chars)."""
    return _SLUG_RE.sub("-", name.lower()).strip("-")[:32]


async def _badge_autocomplete(ctx: discord.AutocompleteContext):
    """This server's badges as a picker: 'Name (slug)' shown, slug
    submitted. Falls back to an empty list on any error so a DB
    hiccup never breaks the command itself."""
    try:
        guild_id = ctx.interaction.guild_id
        if guild_id is None:
            return []
        query = (ctx.value or "").lower()
        badges = await list_custom_badges(str(guild_id))
        choices = [
            discord.OptionChoice(name=f"{b['name']} ({b['slug']})", value=b["slug"])
            for b in badges
            if query in b["name"].lower() or query in b["slug"]
        ]
        return choices[:25]
    except Exception:
        return []


class CustomBadges(commands.Cog):
    """Create, award, and remove mod-awardable custom badges."""

    def __init__(self, bot):
        self.bot = bot

    # ---------- internals ----------

    async def _ensure_db(self):
        try:
            if not database.is_connected:
                await database.connect()
        except Exception as e:
            print(f"[CustomBadges] DB connect check failed: {e!r}")

    async def _resolve_badge(self, ctx, badge_ref):
        """Slug first (what autocomplete submits), then name
        (case-insensitive) for hand-typed input. Returns the badge
        row dict, or None with an error reply already sent."""
        await self._ensure_db()
        badge = await get_custom_badge(str(ctx.guild.id), badge_ref)
        if not badge:
            badge = await get_custom_badge_by_name(str(ctx.guild.id), badge_ref)
        if not badge:
            await ctx.respond(
                f"No badge '{badge_ref}' in this server. "
                "Use /badge list to see this server's badges.",
                ephemeral=True)
            return None
        return badge

    # ---------- commands ----------

    badge = SlashCommandGroup(
        "badge", "Mod-awardable custom badges",
        guild_ids=GUILD_IDS)

    @badge.command(
        name="create",
        description="Create a custom badge for this server.")
    @extra_help("Name: the badge's display name (becomes its slug, unique per server). Icon: emoji shown on the badge shelf (default medal). Description: tooltip text on the badge shelf. Only members with Manage Messages can create badges.")
    @Manage_messages_required()
    async def badge_create(
            self, ctx,
            name: discord.Option(str, "Badge name (e.g. Community MVP)", required=True),
            icon: discord.Option(str, "Emoji for the badge shelf (default: medal)", required=False, default=""),
            description: discord.Option(str, "Tooltip text shown on the badge shelf", required=False, default="")):
        if ctx.guild is None:
            return await ctx.respond(
                "The /badge commands only work in a server.",
                ephemeral=True)
        name = name.strip()
        if not name:
            return await ctx.respond(
                "The badge name cannot be blank.", ephemeral=True)
        if len(name) > _MAX_NAME_LEN:
            return await ctx.respond(
                f"Badge names are at most {_MAX_NAME_LEN} characters.",
                ephemeral=True)
        if len(description or "") > _MAX_DESC_LEN:
            return await ctx.respond(
                f"Badge descriptions are at most {_MAX_DESC_LEN} characters.",
                ephemeral=True)
        if len(icon or "") > _MAX_ICON_LEN:
            return await ctx.respond(
                f"The icon is at most {_MAX_ICON_LEN} characters.",
                ephemeral=True)
        slug = _slugify(name)
        if not slug:
            return await ctx.respond(
                "That name has no letters or digits in it, so it cannot "
                "become a badge slug. Use a name with letters or digits.",
                ephemeral=True)
        await self._ensure_db()
        badge = await create_custom_badge(
            str(ctx.guild.id), slug, name, (icon or "").strip() or "🏅",
            (description or "").strip(), str(ctx.author.id))
        if badge is None:
            return await ctx.respond(
                f"A badge with the slug '{slug}' already exists in this "
                "server. Pick a different name.",
                ephemeral=True)
        await ctx.respond(
            f"Badge created: {(icon or '').strip() or '🏅'} **{name}** "
            f"(slug: `{slug}`). Award it with /badge award.",
            ephemeral=True)

    @badge.command(
        name="award",
        description="Award a custom badge to a member.")
    @extra_help("Badge: pick from this server's badges (or type its name/slug). Member: who receives the badge. Awarded badges appear on their profile badge shelf, and in their activity feed.")
    @Manage_messages_required()
    async def badge_award(
            self, ctx,
            badge_ref: discord.Option(str, "Badge to award (start typing to pick)", required=True, autocomplete=_badge_autocomplete),
            member: discord.Option(discord.Member, "Member to award the badge to", required=True)):
        if ctx.guild is None:
            return await ctx.respond(
                "The /badge commands only work in a server.",
                ephemeral=True)
        if member.bot:
            return await ctx.respond(
                "Bots do not get badges.", ephemeral=True)
        badge = await self._resolve_badge(ctx, badge_ref)
        if badge is None:
            return
        awarded = await award_custom_badge(
            badge["id"], str(ctx.guild.id), str(member.id),
            str(ctx.author.id))
        if not awarded:
            return await ctx.respond(
                f"{member.display_name} already has the **{badge['name']}** badge.",
                ephemeral=True)
        await log_activity(
            str(member.id), str(ctx.guild.id), "badge_award",
            {"badge": badge["name"], "icon": badge["icon"]})
        await ctx.respond(
            f"{badge['icon'] or '🏅'} **{badge['name']}** awarded to "
            f"{member.display_name}. It now shows on their profile badge shelf.",
            ephemeral=True)

    @badge.command(
        name="remove",
        description="Revoke a member's custom badge.")
    @extra_help("Badge: pick from this server's badges (or type its name/slug). Member: whose award is revoked. The badge definition stays and can be awarded again.")
    @Manage_messages_required()
    async def badge_remove(
            self, ctx,
            badge_ref: discord.Option(str, "Badge to revoke (start typing to pick)", required=True, autocomplete=_badge_autocomplete),
            member: discord.Option(discord.Member, "Member to revoke the badge from", required=True)):
        if ctx.guild is None:
            return await ctx.respond(
                "The /badge commands only work in a server.",
                ephemeral=True)
        badge = await self._resolve_badge(ctx, badge_ref)
        if badge is None:
            return
        removed = await remove_custom_badge_award(
            badge["id"], str(member.id))
        if not removed:
            return await ctx.respond(
                f"{member.display_name} does not have the **{badge['name']}** badge.",
                ephemeral=True)
        await ctx.respond(
            f"Revoked **{badge['name']}** from {member.display_name}.",
            ephemeral=True)

    @badge.command(
        name="delete",
        description="Delete a custom badge and all of its awards.")
    @extra_help("Badge: pick from this server's badges (or type its name/slug). Deleting removes the badge from every member who held it; the reply says how many awards were removed. This cannot be undone.")
    @Manage_messages_required()
    async def badge_delete(
            self, ctx,
            badge_ref: discord.Option(str, "Badge to delete (start typing to pick)", required=True, autocomplete=_badge_autocomplete)):
        if ctx.guild is None:
            return await ctx.respond(
                "The /badge commands only work in a server.",
                ephemeral=True)
        badge = await self._resolve_badge(ctx, badge_ref)
        if badge is None:
            return
        removed = await delete_custom_badge(str(ctx.guild.id), badge["slug"])
        await ctx.respond(
            f"Deleted badge **{badge['name']}** and removed it from "
            f"{removed} member(s).",
            ephemeral=True)

    @badge.command(
        name="list",
        description="List this server's custom badges and award counts.")
    @extra_help("Lists every custom badge in this server with its slug and how many members hold it. Anyone with Manage Messages can view the list.")
    @Manage_messages_required()
    async def badge_list(self, ctx):
        if ctx.guild is None:
            return await ctx.respond(
                "The /badge commands only work in a server.",
                ephemeral=True)
        await self._ensure_db()
        badges = await list_custom_badges(str(ctx.guild.id))
        if not badges:
            return await ctx.respond(
                "This server has no custom badges yet. "
                "Create one with /badge create.",
                ephemeral=True)
        lines = []
        for badge in badges:
            count = await count_custom_badge_awards(badge["id"])
            lines.append(
                f"{badge['icon'] or '🏅'} **{badge['name']}** "
                f"(`{badge['slug']}`) -- held by {count} member(s)"
                + (f" -- {badge['description']}" if badge["description"] else ""))
        await ctx.respond("\n".join(lines), ephemeral=True)


def setup(bot):
    bot.add_cog(CustomBadges(bot))
