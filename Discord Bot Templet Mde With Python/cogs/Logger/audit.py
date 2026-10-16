import discord


class Audit:

    @staticmethod
    async def latest(guild, action):

        try:

            async for entry in guild.audit_logs(

                limit=5,

                action=action

            ):

                return entry

        except discord.Forbidden:

            return None

        except Exception:

            return None

        return None

    #
    # -------------------------
    #

    @staticmethod
    async def executor(

        guild,

        action

    ):

        entry = await Audit.latest(

            guild,

            action

        )

        if entry:

            return entry.user

        return None

    #
    # -------------------------
    #

    @staticmethod
    async def reason(

        guild,

        action

    ):

        entry = await Audit.latest(

            guild,

            action

        )

        if entry:

            return entry.reason

        return None