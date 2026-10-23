# web/services/permissions.py
#
# PermissionService: tiered access control for the web dashboard.
#
# Tiers (based on the logged-in user's Discord permission flags for a guild):
#   viewer    - any member of the guild. Can view dashboard, members,
#               channels, leaderboard, etc.
#   moderator - has Kick / Ban / Manage Messages / Timeout Members.
#               Can use the mod panel (warn, timeout, kick, ban, clear...).
#   admin     - has Manage Server / Administrator, or is the guild owner.
#               Can change logger settings and other server configuration.
#
# The permission bitfield comes from Discord's /users/@me/guilds endpoint
# (already cached by web.blueprints.auth.get_user_guilds), so no extra
# API calls are needed here.

from __future__ import annotations


# Discord permission flags (subset we care about).
ADMINISTRATOR = 0x8
MANAGE_GUILD = 0x20
KICK_MEMBERS = 0x2
BAN_MEMBERS = 0x4
MANAGE_MESSAGES = 0x2000
MODERATE_MEMBERS = 1 << 40  # Timeout Members

# Any one of these grants the moderator tier.
MODERATOR_FLAGS = (
    KICK_MEMBERS
    | BAN_MEMBERS
    | MANAGE_MESSAGES
    | MODERATE_MEMBERS
)

# Ordered tiers, lowest first.
ACCESS_LEVELS = ("viewer", "moderator", "admin")


def _level_rank(level: str) -> int:
    try:
        return ACCESS_LEVELS.index(level)
    except ValueError:
        return -1


def get_guild_permission_bits(guild_id) -> int | None:
    """Return the current user's Discord permission bitfield for a guild.

    Returns None when the user is not a member of the guild (or not logged in).
    """
    from web.blueprints.auth import get_user_guilds

    guild_id = str(guild_id)
    for guild in get_user_guilds():
        if str(guild.get("id")) != guild_id:
            continue
        try:
            return int(guild.get("permissions", 0))
        except (TypeError, ValueError):
            return 0
    return None


def is_guild_owner(guild_id) -> bool:
    from web.blueprints.auth import get_user_guilds

    guild_id = str(guild_id)
    for guild in get_user_guilds():
        if str(guild.get("id")) == guild_id:
            return bool(guild.get("owner", False))
    return False


def get_access_level(guild_id) -> str | None:
    """Return 'viewer', 'moderator', 'admin', or None (not a member)."""
    bits = get_guild_permission_bits(guild_id)
    if bits is None:
        return None
    if bits & ADMINISTRATOR:
        return "admin"
    if is_guild_owner(guild_id):
        return "admin"
    if bits & MANAGE_GUILD:
        return "admin"
    if bits & MODERATOR_FLAGS:
        return "moderator"
    return "viewer"


def is_guild_member(guild_id) -> bool:
    """True when the logged-in user is a member of the guild (any tier)."""
    return get_access_level(guild_id) is not None


def has_access(guild_id, level: str) -> bool:
    """True when the user's tier meets or exceeds the required level."""
    if level not in ACCESS_LEVELS:
        return False
    user_level = get_access_level(guild_id)
    if user_level is None:
        return False
    return _level_rank(user_level) >= _level_rank(level)


# Backwards-compatible alias used by older code paths.
def user_can_manage_guild(guild_id) -> bool:
    return has_access(guild_id, "admin")
