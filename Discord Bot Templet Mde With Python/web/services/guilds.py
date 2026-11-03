"""Guild data service -- bridge client (BRIDGE_CONTRACT.md section 6).

Same public interface and return shapes as before, but every live
Discord read goes through the bot-side bridge instead of the live bot
object. The bridge returns guild dicts in the ServerService
serialize_guild() shape; this module maps them onto the shapes its
existing callers expect. The Logger-DB event helpers are unchanged --
they read the local message_log database, not Discord.
"""
from flask import current_app
from web.services import bridge
from web.services.bridge import BridgeUnavailable
from web.services.logger_db import logger_db as database


class GuildService:

    def get_bot(self):
        # No live bot object in the website process any more.
        return None

    def get_guild(self, guild_id):

        try:

            guild_id = int(guild_id)

        except (TypeError, ValueError):

            print(
                f"[GuildService] Invalid guild ID: {guild_id}"
            )

            return None

        try:
            guild = bridge.get_guild(guild_id)
        except BridgeUnavailable:
            print(
                "[GuildService] Bridge is not reachable."
            )
            return None

        if guild is None:

            print(
                f"[GuildService] Guild not found: {guild_id}"
            )

            return None

        from web.services.bridge import wrap

        return wrap(guild)

    def get_guild_event_statistics(self, guild_id):
        # TODO(webui): re-point at new Logger schema (old logger_events SQL removed)
        return {
            "total_events": 0,
            "message_deleted": 0,
            "message_edited": 0,
            "member_events": 0,
            "voice_events": 0,
            "role_events": 0,
            "server_events": 0
        }

    def get_recent_events(self, guild_id, limit=10):
        # TODO(webui): re-point at new Logger schema (old logger_events SQL removed)
        return []

    def get_guilds(self):

        try:
            guilds = bridge.get_guilds()
        except BridgeUnavailable:
            return []

        servers = []

        for guild in guilds:

            servers.append({

                "id": str(guild.get("id")),

                "guild_id": str(guild.get("id")),

                "name": guild.get("name"),

                "member_count":
                    int(guild.get("member_count") or 0),

                "channel_count":
                    int(guild.get("channel_count") or 0),

                "event_count":
                    database.count_events(guild.get("id")),

                "icon":
                    guild.get("icon"),

            })

        return servers

    def search_events(
        self,
        guild_id,
        limit=50,
        category=None,
        event_type=None,
        search=None
    ):
        return database.search_events(
            guild_id, search=search, category=category,
            event_type=event_type, limit=min(limit, 200),
        )

    def get_guild_info(self, guild_id):

        guild = self.get_guild(
            guild_id
        )

        if guild is None:
            return None

        owner = None

        try:

            if guild.get("owner_id"):

                owner = {
                    "id":
                        str(guild.get("owner_id")),

                    "name":
                        guild.get("owner_name"),

                    "display_name":
                        guild.get("owner_name"),

                    "avatar":
                        guild.get("owner_avatar"),
                }

        except Exception:

            owner = None

        return {

            "success":
                True,

            "id":
                str(guild.get("id")),

            "guild_id":
                str(guild.get("id")),

            "name":
                guild.get("name"),

            "description":
                guild.get("description"),

            "icon":
                guild.get("icon"),

            "banner":
                guild.get("banner"),

            "owner": owner,

            "owner_id":
                (
                    str(guild.get("owner_id"))
                    if guild.get("owner_id")
                    else None
                ),

            "member_count": int(guild.get("member_count") or 0),

            "channel_count": int(guild.get("channel_count") or 0),

            "text_channel_count":
                int(guild.get("text_channel_count") or 0),

            "voice_channel_count":
                int(guild.get("voice_channel_count") or 0),

            "category_count":
                int(guild.get("category_count") or 0),

            "role_count":
                int(guild.get("role_count") or 0),

            "event_count":
                self.get_guild_event_statistics(
                    guild.get("id")
                ).get(
                    "total_events",
                    0
                ),

            "emoji_count":
                int(guild.get("emoji_count") or 0),

            "sticker_count":
                int(guild.get("sticker_count") or 0),

            "created_at":
                guild.get("created_at"),

            "verification_level":
                str(guild.get("verification_level", "unknown")),

            "default_notifications":
                str(guild.get("default_notifications", "unknown")),

            "explicit_content_filter":
                str(guild.get("explicit_content_filter", "unknown")),

            "premium_tier":
                int(guild.get("premium_tier") or 0),

            "premium_subscription_count":
                int(guild.get("premium_subscription_count") or 0),

            "features":
                list(guild.get("features") or []),
    }

    def get_guild_statistics(self, guild_id):

        guild = self.get_guild(
            guild_id
        )

        if guild is None:
            return None

        return {

            "members":
                int(guild.get("member_count") or 0),

            "channels":
                int(guild.get("channel_count") or 0),

            "text_channels":
                int(guild.get("text_channel_count") or 0),

            "voice_channels":
                int(guild.get("voice_channel_count") or 0),

            "categories":
                int(guild.get("category_count") or 0),

            "roles":
                int(guild.get("role_count") or 0),

            "emojis":
                int(guild.get("emoji_count") or 0),

            "stickers":
                int(guild.get("sticker_count") or 0),

        }

    def get_guild_channels(self, guild_id):

        try:
            channels = bridge.get_channels(guild_id)
        except BridgeUnavailable:
            return None

        if channels is None:

            return None

        return [
            {
                "id": str(channel.get("id")),
                "name": channel.get("name"),
                "type": channel.get("type"),
                "position": channel.get("position"),
                "category": channel.get("category"),
            }
            for channel in channels
        ]


guilds = GuildService()
