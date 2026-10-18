import discord


class ServerService:
    """Discord guild data service used by the web dashboard."""

    def __init__(self, bot):
        self.bot = bot

    def get_guild(self, guild_id):
        if self.bot is None:
            return None
        try:
            guild_id = int(guild_id)
        except (TypeError, ValueError):
            return None
        try:
            if not self.bot.is_ready():
                return None
        except Exception:
            return None
        return self.bot.get_guild(guild_id)

    @staticmethod
    def _asset_url(asset):
        try:
            return str(asset.url) if asset else None
        except Exception:
            return None

    def serialize_guild(self, guild):
        members = list(getattr(guild, 'members', []) or [])
        channels = list(getattr(guild, 'channels', []) or [])
        roles = list(getattr(guild, 'roles', []) or [])
        text_channels = [c for c in channels if isinstance(c, discord.TextChannel)]
        voice_channels = [c for c in channels if isinstance(c, discord.VoiceChannel)]
        categories = [c for c in channels if isinstance(c, discord.CategoryChannel)]
        stage_channels = [c for c in channels if isinstance(c, discord.StageChannel)]
        forum_channels = [c for c in channels if isinstance(c, discord.ForumChannel)]
        owner_name = None
        owner_avatar = None
        try:
            if guild.owner:
                owner_name = guild.owner.display_name
                owner_avatar = self._asset_url(guild.owner.display_avatar)
        except Exception:
            pass
        return {
            'id': str(guild.id),
            'name': guild.name,
            'description': getattr(guild, 'description', None),
            'icon': self._asset_url(getattr(guild, 'icon', None)),
            'banner': self._asset_url(getattr(guild, 'banner', None)),
            'owner_id': str(guild.owner_id) if getattr(guild, 'owner_id', None) else None,
            'owner_name': owner_name,
            'owner_avatar': owner_avatar,
            'created_at': guild.created_at.isoformat() if getattr(guild, 'created_at', None) else None,
            'verification_level': str(getattr(guild, 'verification_level', 'unknown')),
            'preferred_locale': str(getattr(guild, 'preferred_locale', 'unknown')),
            'premium_tier': int(getattr(guild, 'premium_tier', 0) or 0),
            'premium_subscription_count': int(getattr(guild, 'premium_subscription_count', 0) or 0),
            'features': list(getattr(guild, 'features', []) or []),
            'member_count': int(getattr(guild, 'member_count', 0) or len(members) or 0),
            'channel_count': len(channels),
            'text_channel_count': len(text_channels),
            'voice_channel_count': len(voice_channels),
            'category_count': len(categories),
            'stage_channel_count': len(stage_channels),
            'forum_channel_count': len(forum_channels),
            'role_count': len(roles),
            'emoji_count': len(getattr(guild, 'emojis', []) or []),
            'sticker_count': len(getattr(guild, 'stickers', []) or []),
        }

    def overview(self, guild_id):
        guild = self.get_guild(guild_id)
        return self.serialize_guild(guild) if guild else None

    def get_servers(self):
        if self.bot is None:
            return []
        try:
            if not self.bot.is_ready():
                return []
        except Exception:
            return []
        return [self.serialize_guild(guild) for guild in self.bot.guilds]

    def get_dashboard(self, guild_id):
        guild = self.get_guild(guild_id)
        if guild is None:
            return None

        members = list(guild.members)
        channels = list(guild.channels)
        roles = list(guild.roles)
        humans = [m for m in members if not m.bot]
        bots = [m for m in members if m.bot]
        online = sum(1 for m in members if str(getattr(m, 'status', 'offline')) == 'online')
        idle = sum(1 for m in members if str(getattr(m, 'status', 'offline')) == 'idle')
        dnd = sum(1 for m in members if str(getattr(m, 'status', 'offline')) in {'dnd', 'do_not_disturb'})
        offline = len(members) - online - idle - dnd
        text = [c for c in channels if isinstance(c, discord.TextChannel)]
        voice = [c for c in channels if isinstance(c, discord.VoiceChannel)]
        categories = [c for c in channels if isinstance(c, discord.CategoryChannel)]
        stage = [c for c in channels if isinstance(c, discord.StageChannel)]
        forum = [c for c in channels if isinstance(c, discord.ForumChannel)]
        managed = [r for r in roles if r.managed]
        custom = [r for r in roles if not r.managed and r.name != '@everyone']
        admin_roles = [r for r in custom if r.permissions.administrator]
        # Real event data from the Logger events table.
        try:
            from web.services.logger_db import logger_db
            event_count = logger_db.count_events(guild_id)
            recent_events = logger_db.query_events(guild_id, limit=10)
        except Exception:
            event_count = 0
            recent_events = []
        member_count = int(getattr(guild, 'member_count', 0) or len(members))
        return {
            'server': self.serialize_guild(guild),
            'members': {'count': member_count, 'total': len(members), 'humans': len(humans), 'bots': len(bots), 'online': online, 'idle': idle, 'dnd': dnd, 'offline': max(0, offline)},
            'channels': {'count': len(channels), 'total': len(channels), 'categories': len(categories), 'text': len(text), 'voice': len(voice), 'stage': len(stage), 'forum': len(forum)},
            'roles': {'count': len(roles), 'total': len(roles), 'custom': len(custom), 'managed': len(managed), 'administrator': len(admin_roles)},
            'events': {'count': event_count, 'total': event_count},
            'channel_list': [
                {
                    'id': c.id,
                    'name': c.name,
                    'type': type(c).__name__,
                }
                for c in channels
            ],
            'statistics': {
                'members': len(members),
                'humans': len(humans),
                'bots': len(bots),
                'online': online,
                'idle': idle,
                'dnd': dnd,
                'offline': max(0, offline),
                'channels': len(channels),
                'text_channels': len(text),
                'voice_channels': len(voice),
                'categories': len(categories),
                'roles': len(roles),
            },
            'recent_events': recent_events,
            'event_statistics': {'total': event_count},
            'bot': {'ready': bool(self.bot.is_ready()), 'latency_ms': round(float(getattr(self.bot, 'latency', 0) or 0) * 1000, 2)},
        }
