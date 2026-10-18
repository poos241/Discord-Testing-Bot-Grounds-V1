import discord


class WebPermissionError(Exception):
    pass


class PermissionService:

    def __init__(self, bot):
        self.bot = bot

    # ----------------------------------------------
    # Guild
    # ----------------------------------------------

    def get_guild(
        self,
        guild_id
    ):

        guild = self.bot.get_guild(
            int(guild_id)
        )

        if guild is None:
            raise WebPermissionError(
                "Guild not found."
            )

        return guild

    # ----------------------------------------------
    # Member
    # ----------------------------------------------

    def get_member(
        self,
        guild_id,
        user_id
    ):

        guild = self.get_guild(
            guild_id
        )

        member = guild.get_member(
            int(user_id)
        )

        if member is None:
            raise WebPermissionError(
                "User is not a member of this server."
            )

        return member

    # ----------------------------------------------
    # Administrator
    # ----------------------------------------------

    def is_admin(
        self,
        guild_id,
        user_id
    ):

        member = self.get_member(
            guild_id,
            user_id
        )

        return (
            member.guild_permissions.administrator
        )

    # ----------------------------------------------
    # Specific permission
    # ----------------------------------------------

    def has_permission(
        self,
        guild_id,
        user_id,
        permission
    ):

        member = self.get_member(
            guild_id,
            user_id
        )

        permissions = member.guild_permissions

        return getattr(
            permissions,
            permission,
            False
        )

    # ----------------------------------------------
    # Can moderate
    # ----------------------------------------------

    def can_moderate(
        self,
        guild_id,
        moderator_id,
        target_id
    ):

        guild = self.get_guild(
            guild_id
        )

        moderator = self.get_member(
            guild_id,
            moderator_id
        )

        target = self.get_member(
            guild_id,
            target_id
        )

        # Server owner can do everything
        if moderator.id == guild.owner_id:
            return True

        # Must have moderation permission
        if not (
            moderator.guild_permissions.moderate_members
            or
            moderator.guild_permissions.administrator
        ):
            return False

        # Cannot moderate owner
        if target.id == guild.owner_id:
            return False

        # Cannot moderate yourself
        if target.id == moderator.id:
            return False

        # Role hierarchy
        if target.top_role >= moderator.top_role:
            return False

        return True