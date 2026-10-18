import discord
from datetime import timedelta

class ModerationError(Exception):
    pass


class ModerationService:

    def __init__(self, bot):
        self.bot = bot

    # --------------------------------------------------
    # Get guild
    # --------------------------------------------------

    def get_guild(self, guild_id: int):

        guild = self.bot.get_guild(int(guild_id))

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
        guild: discord.Guild,
        user_id: int
    ):

        member = guild.get_member(int(user_id))

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
        guild: discord.Guild,
        member: discord.Member
    ):

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

        guild = self.get_guild(
            guild_id
        )

        member = self.get_member(
            guild,
            user_id
        )

        self.can_moderate(
            guild,
            member
        )

        if duration <= 0:
            raise ModerationError(
                "Timeout duration must be greater than zero."
            )

        if duration > 28 * 24 * 60 * 60:
            raise ModerationError(
                "Timeout cannot exceed 28 days."
            )

        await member.timeout_for(
            timedelta(seconds=duration),
            reason=reason
        )

        return member

    # --------------------------------------------------
    # Remove timeout
    # --------------------------------------------------

    async def remove_timeout(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):

        guild = self.get_guild(guild_id)

        member = self.get_member(
            guild,
            user_id
        )

        self.can_moderate(
            guild,
            member
        )

        await member.remove_timeout(
            reason=reason
        )

        return member

    # --------------------------------------------------
    # Kick
    # --------------------------------------------------

    async def kick(
        self,
        guild_id: int,
        user_id: int,
        reason: str | None = None
    ):

        guild = self.get_guild(guild_id)

        member = self.get_member(
            guild,
            user_id
        )

        self.can_moderate(
            guild,
            member
        )

        await member.kick(
            reason=reason
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

        guild = self.get_guild(guild_id)

        member = guild.get_member(
            int(user_id)
        )

        if member:
            self.can_moderate(
                guild,
                member
            )

        await guild.ban(
            discord.Object(id=int(user_id)),
            reason=reason,
            delete_message_days=delete_message_days
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

        guild = self.get_guild(guild_id)

        user = discord.Object(
            id=int(user_id)
        )

        await guild.unban(
            user,
            reason=reason
        )

        return True