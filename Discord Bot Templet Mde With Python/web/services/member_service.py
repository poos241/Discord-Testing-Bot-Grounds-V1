

class MemberService:  # presence-status-update

    def __init__(self, bot):
        self.bot = bot

    # ---------------------------------------------
    # GET GUILD
    # ---------------------------------------------

    def get_guild(self, guild_id):

        if self.bot is None:
            return None

        return self.bot.get_guild(
            int(guild_id)
        )

    # ---------------------------------------------
    # GET MEMBER
    # ---------------------------------------------

    def get_member(
        self,
        guild_id,
        user_id
    ):

        guild = self.get_guild(
            guild_id
        )

        if guild is None:
            return None

        return guild.get_member(
            int(user_id)
        )

    # ---------------------------------------------
    # GET ALL MEMBERS
    # ---------------------------------------------

    def get_members(
        self,
        guild_id
    ):

        guild = self.get_guild(
            guild_id
        )

        if guild is None:
            return []

        return list(
            guild.members
        )

    # ---------------------------------------------
    # SERIALIZE MEMBER
    # ---------------------------------------------

    def serialize_member(
        self,
        member
    ):

        if member is None:
            return None

        return {
            "id":
                str(member.id),

            "username":
                member.name,

            "display_name":
                member.display_name,

            "nickname":
                member.nick,

            "bot":
                member.bot,

            "status":
                str(member.status) if hasattr(member, "status") else "offline",

            "avatar": (
                str(member.display_avatar.url)
                if member.display_avatar
                else None
            ),

            "created_at": (
                member.created_at.isoformat()
                if member.created_at
                else None
            ),

            "joined_at": (
                member.joined_at.isoformat()
                if member.joined_at
                else None
            ),

            "roles": [
                {
                    "id":
                        str(role.id),

                    "name":
                        role.name,

                    "position":
                        role.position,

                    "color":
                        str(role.color),
                }

                for role in member.roles

                if role.name != "@everyone"
            ],

            "top_role": {
                "id":
                    str(member.top_role.id),

                "name":
                    member.top_role.name,

                "position":
                    member.top_role.position,
            },

            "permissions": [
                permission

                for permission, enabled
                in member.guild_permissions

                if enabled
            ],
        }

    

    # ---------------------------------------------
    # SEARCH MEMBERS
    # ---------------------------------------------

    def search_members(
        self,
        guild_id,
        query
    ):

        members = self.get_members(
            guild_id
        )

        if not query:
            return members

        query = str(
            query
        ).lower()

        results = []

        for member in members:

            username = (
                member.name or ""
            ).lower()

            display_name = (
                member.display_name or ""
            ).lower()

            nickname = (
                member.nick or ""
            ).lower()

            member_id = str(
                member.id
            )

            if (
                query in username
                or
                query in display_name
                or
                query in nickname
                or
                query in member_id
            ):

                results.append(
                    member
                )

        return results