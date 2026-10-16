"""Helper for reading Discord's audit log."""
import discord


class Audit:
    @staticmethod
    async def latest(guild, action, target_id=None, limit=5):
        """Return the most recent audit-log entry for an action.

        When target_id is given, only entries targeting that user/channel
        are considered, so the moderator/reason actually match the event.
        """
        try:
            async for entry in guild.audit_logs(limit=limit, action=action):
                if target_id is None:
                    return entry
                target = entry.target
                if target is not None and getattr(target, "id", None) == target_id:
                    return entry
        except (discord.Forbidden, discord.HTTPException):
            return None
        return None
