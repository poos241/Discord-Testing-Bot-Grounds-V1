"""Moderation service -- bridge client (BRIDGE_CONTRACT.md section 6).

Same class and method signatures as before, so the moderation blueprint
keeps calling ``service.timeout(...)`` etc. through
``run_coro_threadsafe`` exactly as today. The methods stay async; their
internals call the sync bridge client on a worker thread (asyncio.to_thread)
so the website's local loop is never blocked by a bridge round-trip.

Hierarchy enforcement (``can_moderate``) stays bot-side: the bridge
handler performs the bot-hierarchy check and answers 403, which
arrives here as BridgeError(403) and is re-raised as ModerationError,
exactly like the old local check. There is no live guild/member object
in this process any more, so ``can_moderate`` itself cannot evaluate a
check here -- it raises loudly instead of pretending to.
"""

import asyncio

from web.services import bridge
from web.services.bridge import BridgeError, BridgeUnavailable, wrap


class ModerationError(Exception):
    pass


class ModerationService:

    def __init__(self, bot=None):
        # Kept for call-site compat (ModerationService(bot) /
        # ModerationService()). The website passes no bot: all actions
        # go through the bridge. The bot-side bridge passes the live
        # bot so can_moderate() can run the hierarchy check (see DUAL
        # MODE note in server_service.py; before this fix can_moderate
        # raised on every call, so every bridge timeout/kick/ban
        # answered 403). Action methods stay bridge-only by design:
        # the bridge performs them directly on discord objects.
        self.bot = bot

    @property
    def _live(self):
        """True when constructed with a live discord bot object."""
        return self.bot is not None and hasattr(self.bot, "get_guild")

    # --------------------------------------------------
    # Helpers
    # --------------------------------------------------

    async def _bridge(self, func, *args, **kwargs):
        """Run one bridge call off-loop; map bridge failures onto
        ModerationError so blueprint _fail() keeps its 400 shape --
        EXCEPT BridgeUnavailable (bot down), which is re-raised as-is
        so callers can answer 503 instead of 400. Collapsing it into
        ModerationError hid "bot is down" behind a 400."""
        try:
            return await asyncio.to_thread(func, *args, **kwargs)
        except BridgeUnavailable:
            raise
        except BridgeError as exc:
            raise ModerationError(exc.message)

    @staticmethod
    def _guild_id(guild):
        if isinstance(guild, dict):
            return guild.get("id")
        return getattr(guild, "id", guild)

    # --------------------------------------------------
    # Get guild
    # --------------------------------------------------

    def get_guild(self, guild_id: int):
        guild = bridge.get_guild(guild_id)
        if guild is None:
            raise ModerationError(
                "Guild is not available to the bot."
            )
        return guild

    # --------------------------------------------------
    # Get member
    # --------------------------------------------------

    def get_member(
        self,
        guild,
        user_id: int
    ):
        member = bridge.get_member(self._guild_id(guild), user_id)
        if member is None:
            raise ModerationError(
                "Member was not found."
            )
        return member

    # --------------------------------------------------
    # Bot hierarchy check
    # --------------------------------------------------

    def can_moderate(
        self,
        guild,
        member
    ):
        """Enforced bot-side by the bridge handler now.

        Live path (constructed with the bot): the real hierarchy
        check -- bot must outrank the target and the target must not
        be the bot itself or the server owner. Website path (no bot):
        raises loudly, as before -- there is no live guild/member
        object in the website process to evaluate, and a silent True
        here would be a lie. Action methods do not call this any
        more -- the bridge answers 403 on a hierarchy refusal.
        """
        if self._live:
            me = guild.me

            if me is None:
                raise ModerationError(
                    "Bot member could not be found."
                )

            if member.id == me.id:
                raise ModerationError(
                    "The bot cannot moderate itself."
                )

            if member.id == guild.owner_id:
                raise ModerationError(
                    "The server owner cannot be moderated."
                )

            if member.top_role >= me.top_role:
                raise ModerationError(
                    "The bot's highest role is not high enough."
                )

            return True

        raise ModerationError(
            "Hierarchy checks are enforced by the bot-side bridge; "
            "can_moderate cannot run in the website process."
        )

    # --------------------------------------------------
    # Timeout
    # --------------------------------------------------

    async def timeout(
    self,
    guild_id: int,
    user_id: int,
    duration: int,
    reason: str | None = None
    ):

        if duration <= 0:
            raise ModerationError(
                "Timeout duration must be greater than zero."
            )

        if duration > 28 * 24 * 60 * 60:
            raise ModerationError(
                "Timeout cannot exceed 28 days."
            )

        return wrap(
            await self._bridge(
                bridge.timeout, guild_id, user_id, duration, reason
            )
        )

    # --------------------------------------------------
    # Remove timeout
    # --------------------------------------------------

    async def remove_timeout(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):

        return wrap(
            await self._bridge(
                bridge.untimeout, guild_id, user_id, reason
            )
        )

    # --------------------------------------------------
    # Kick
    # --------------------------------------------------

    async def kick(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):

        await self._bridge(
            bridge.kick, guild_id, user_id, reason
        )

        return True

    # --------------------------------------------------
    # Ban
    # --------------------------------------------------

    async def ban(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None,
        delete_message_days: int = 0
    ):

        await self._bridge(
            bridge.ban, guild_id, user_id, reason, delete_message_days
        )

        return True

    # --------------------------------------------------
    # Unban
    # --------------------------------------------------

    async def unban(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):

        await self._bridge(
            bridge.unban, guild_id, user_id, reason
        )

        return True

    # --------------------------------------------------
    # Rename (bridge action; used by the mod panel)
    # --------------------------------------------------

    async def rename(
        self,
        guild_id: int,
        user_id: int,
        nickname: str | None
    ):

        if nickname is not None and len(nickname) > 32:
            raise ModerationError(
                "Nickname cannot be longer than 32 characters."
            )

        return wrap(
            await self._bridge(
                bridge.rename, guild_id, user_id, nickname
            )
        )

    # --------------------------------------------------
    # Strip roles (bridge action; used by the mod panel)
    # --------------------------------------------------

    async def strip_roles(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):
        """Returns {removed: [...], skipped: [...]} (partial success)."""
        return await self._bridge(
            bridge.strip_roles, guild_id, user_id, reason
        )

    # --------------------------------------------------
    # Purge (bridge action; used by the mod panel)
    # --------------------------------------------------

    async def purge(
        self,
        guild_id: int,
        channel_id: int,
        user_id: int | None = None,
        limit: int = 100
    ):
        """Returns {deleted: <int>}."""
        return await self._bridge(
            bridge.purge, guild_id, channel_id, user_id, limit
        )

    # --------------------------------------------------
    # DM (bridge action; used by the mod panel)
    # --------------------------------------------------

    async def send_dm(
        self,
        guild_id: int,
        user_id: int,
        text: str
    ):
        """Returns {sent: bool}."""
        return await self._bridge(
            bridge.send_dm, guild_id, user_id, text
        )

    # --------------------------------------------------
    # Award XP (bridge action; used by the mod panel)
    # --------------------------------------------------

    async def award_xp(
        self,
        guild_id: int,
        user_id: int,
        amount: int,
        display_name: str | None = None
    ):
        """Returns {xp, level} as the bot's award_xp reports them."""
        return await self._bridge(
            bridge.award_xp, guild_id, user_id, amount, display_name
        )
