"""Shared embed builders for log messages.

Style: the log embeds match the Introduction cog's Havenly embeds
(cogs/Introduction.py, _havenly_embed): an emoji + Title Case title,
the facts carried in the description as bold-label lines
("**User:** @mention [username] (id)"), a semantic color from the
Havenly palette (green = created/joined/added, blue = edited/updated/
informational, yellow = mixed/caution, red = deleted/removed/banned),
a timestamp, and the "Powered by Havenly Bot" footer. The affected
user is also set as the embed author (name + avatar) so the log line
carries their picture. Fields are used only for structured detail
that does not fit the description (long content, role lists, diffs).
No thumbnails: the intro style uses none, and the author icon
already shows the affected user's avatar. Content images (a changed
avatar, a deleted message's image, an emoji, the banned user's pfp)
are kept -- they are the payload, not decoration.
"""
import discord

from .config import FOOTER_TEXT

# The Havenly bot's exact log-embed colors (discord.js Colors.*),
# as used by the Introduction cog. Semantic, not per-category:
# green = created / joined / added, blue = edited / updated / info,
# yellow = mixed / caution, red = deleted / removed / banned.
HAVENLY_GREEN = 0x57F287
HAVENLY_BLUE = 0x3498DB
HAVENLY_YELLOW = 0xFEE75C
HAVENLY_RED = 0xED4245


def user_line(user, user_id=None):
    """One user as the Havenly logs show them: `@Duke [xduke_br] (id)`.

    The mention renders the display name; the bracket holds the
    username; the id is in parens. When only an id is known (member
    left), fall back to a raw mention plus the id. Mirrors
    Introduction._log_user_line.
    """
    if user is not None:
        return f"{user.mention} [{user.name}] ({user.id})"
    return f"<@{user_id}> ({user_id})"


def role_line(role):
    """One role as the Havenly logs show it: `@Role [Role Name]`."""
    return f"{role.mention} [{role.name}]"


def _truncate_lines(text, limit=1024):
    """Cut over-long text to fit a field, on a line boundary.

    Discord caps a field value at 1024 chars; cutting mid-line can
    split a mention or a code span, so the cut backs up to the last
    newline inside the limit and notes the truncation. Falls back to
    a hard cut only when the text has no usable newline.
    """
    if len(text) <= limit:
        return text
    suffix = "\n... (truncated)"
    cut = text[: limit - len(suffix)]
    newline = cut.rfind("\n")
    if newline > 100:
        return cut[:newline] + suffix
    return text[: limit - 3] + "..."


class LoggerEmbed:
    # Semantic Havenly colors, as class attributes so call sites read
    # LoggerEmbed.GREEN / .BLUE / .YELLOW / .RED.
    GREEN = HAVENLY_GREEN
    BLUE = HAVENLY_BLUE
    YELLOW = HAVENLY_YELLOW
    RED = HAVENLY_RED

    @staticmethod
    def base(title, color, description=None):
        return discord.Embed(
            title=title,
            color=color,
            description=description,
            timestamp=discord.utils.utcnow(),
        )

    @staticmethod
    def author(embed, user):
        embed.set_author(
            name=f"{user} ({user.id})",
            icon_url=user.display_avatar.url,
        )
        return embed

    @staticmethod
    def footer(embed, text=FOOTER_TEXT):
        embed.set_footer(text=text)
        return embed

    @staticmethod
    def field(embed, name, value, inline=False):
        text = str(value) if value not in (None, "") else "None"
        text = _truncate_lines(text)
        embed.add_field(name=name, value=text, inline=inline)
        return embed

    @staticmethod
    def finalize(embed):
        """Apply the standard footer. Call after building the embed."""
        return LoggerEmbed.footer(embed)
