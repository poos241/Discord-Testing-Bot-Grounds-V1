from flask import current_app
from web.services.logger_db import logger_db as database
class GuildService:

    def get_bot(self):

        bot = current_app.config.get(
            "DISCORD_BOT"
        )

        if bot is None:
            bot = current_app.config.get(
                "BOT"
            )

        return bot


    def get_guild(self, guild_id):

        bot = self.get_bot()

        if bot is None:

            print(
                "[GuildService] Discord bot is not connected."
            )

            return None

        if not bot.is_ready():

            print(
                "[GuildService] Discord bot is not ready."
            )

            return None

        try:

            guild_id = int(guild_id)

        except (TypeError, ValueError):

            print(
                f"[GuildService] Invalid guild ID: {guild_id}"
            )

            return None

        guild = bot.get_guild(
            guild_id
        )

        if guild is None:

            print(
                f"[GuildService] Guild not found: {guild_id}"
            )

            return None

        return guild

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

        bot = self.get_bot()

        if bot is None:
            return []

        if not bot.is_ready():
            return []

        servers = []

        for guild in bot.guilds:

            servers.append({

                "id": str(guild.id),

                "guild_id": str(guild.id),

                "name": guild.name,

                "member_count":
                    guild.member_count or 0,

                "channel_count":
                    len(guild.channels),

                "event_count":
                    database.count_events(guild.id),

                "icon":
                    (
                        str(guild.icon.with_size(128).url)
                        if guild.icon
                        else None
                    )

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

            if guild.owner:

                owner = {
                    "id":
                        str(guild.owner.id),

                    "name":
                        guild.owner.name,

                    "display_name":
                        guild.owner.display_name,

                    "avatar":
                        (
                            str(guild.owner.display_avatar.url)
                            if guild.owner.display_avatar
                            else None
                        )
                }

        except Exception:

            owner = None


        icon = None

        try:

            if guild.icon:
                icon = str(
                    guild.icon.with_size(128).url
                )

        except Exception:

            icon = None


        banner = None

        try:

            if guild.banner:
                banner = str(
                    guild.banner.url
                )

        except Exception:

            banner = None


        return {

            "success":
                True,

            "id":
                str(guild.id),

            "guild_id":
                str(guild.id),

            "name":
                guild.name,

            "description":
                guild.description,

            "icon":
                icon,

            "banner":
                banner,

            "owner":
                owner,

            "owner_id":
                (
                    str(guild.owner_id)
                    if guild.owner_id
                    else None
                ),

            "member_count":
                guild.member_count or 0,

            "channel_count":
                len(guild.channels),

            "text_channel_count":
                len(guild.text_channels),

            "voice_channel_count":
                len(guild.voice_channels),

            "category_count":
                len(guild.categories),

            "role_count":
            len(guild.roles),

            "event_count":
                self.get_guild_event_statistics(
                    guild.id
                ).get(
                    "total_events",
                    0
                ),

            "emoji_count":
                len(guild.emojis),

            "sticker_count":
                len(guild.stickers),

            "created_at":
                (
                    guild.created_at.isoformat()
                    if guild.created_at
                    else None
                ),

            "verification_level":
                str(
                    guild.verification_level
                ),

            "default_notifications":
                str(
                    guild.default_notifications
                ),

            "explicit_content_filter":
                str(
                    guild.explicit_content_filter
                ),

            "premium_tier":
                getattr(
                    guild,
                    "premium_tier",
                    0
                ),

            "premium_subscription_count":
                getattr(
                    guild,
                    "premium_subscription_count",
                    0
                ),

            "features":
                list(
                    guild.features
                )
    }

    def get_guild_statistics(self, guild_id):

        guild = self.get_guild(
            guild_id
        )

        if guild is None:
            return None


        text_channels = len(
            guild.text_channels
        )

        voice_channels = len(
            guild.voice_channels
        )

        categories = len(
            guild.categories
        )


        return {

            "members":
                guild.member_count or 0,

            "channels":
                len(guild.channels),

            "text_channels":
                text_channels,

            "voice_channels":
                voice_channels,

            "categories":
                categories,

            "roles":
                len(guild.roles),

            "emojis":
                len(guild.emojis),

            "stickers":
                len(guild.stickers)

        }
    
    def get_guild_channels(self, guild_id):

        guild = self.get_guild(
            guild_id
        )


        if guild is None:

            return None


        channels = []


        for channel in guild.channels:

            if channel in guild.text_channels:

                channel_type = "text"

            elif channel in guild.voice_channels:

                channel_type = "voice"

            elif channel in guild.categories:

                channel_type = "category"

            else:

                channel_type = "other"


            channels.append({

                "id":
                    str(channel.id),

                "name":
                    channel.name,

                "type":
                    channel_type,

                "position":
                    channel.position,

                "category":
                    (
                        channel.category.name
                        if channel.category
                        else None
                    )

            })


        return channels


guilds = GuildService()