"""Discord guild data service -- bridge client (BRIDGE_CONTRACT.md section 6).

Same public interface as before (overview / get_servers / get_dashboard
/ serialize_guild / get_guild), but every read goes through the bot-side
bridge instead of the live bot object. The bridge returns guild dicts in
the serialize_guild() shape (the bot side computes them with the same
serializer), so blueprints see identical data.

``serialize_guild`` stays as the shape reference: it normalises a bridge
guild dict, filling the same keys the old discord.py version produced.

DUAL MODE (2026-11-02 fix): this module is ALSO imported by the bot
process (bridge_api.py), where it is constructed with the live bot and
must answer from live discord.py objects. When ``bot`` is a live bot
object the methods below take the live path (the same logic the bridge
harness proved); otherwise they take the bridge-client path. The
website always constructs ServerService() with no bot, so its path is
unchanged. Before this fix the live path was missing entirely:
serialize_guild raised TypeError on a live guild (so /bridge/guilds
500'd) and get_dashboard called back into the bridge (self-recursion),
which is why the bridge harness -- which runs against its own live
copies -- never caught it.
"""

import discord

from web.services import bridge
from web.services.bridge import BridgeUnavailable, wrap


class ServerService:
    """Discord guild data service used by the web dashboard."""

    def __init__(self, bot=None):
        # Kept for call-site compat (ServerService(bot) /
        # ServerService()). The website passes no bot (bridge path);
        # the bot-side bridge passes the live bot (live path).
        self.bot = bot

    @property
    def _live(self):
        """True when constructed with a live discord bot object."""
        return self.bot is not None and hasattr(self.bot, "get_guild")

    @staticmethod
    def _asset_url(asset):
        try:
            return str(asset.url) if asset else None
        except Exception:
            return None

    def get_guild(self, guild_id):
        if self._live:
            if self.bot is None:
                return None
            try:
                if not self.bot.is_ready():
                    return None
            except Exception:
                return None
            try:
                return self.bot.get_guild(int(guild_id))
            except (TypeError, ValueError):
                return None
        try:
            guild = bridge.get_guild(guild_id)
            return wrap(guild) if guild is not None else None
        except BridgeUnavailable:
            return None

    def serialize_guild(self, guild):
        """Normalise a guild into the documented shape.

        Accepts a bridge guild dict (website path) or a live discord.py
        Guild (bot-side bridge path); both produce the same keys.
        """
        if guild is None:
            return None
        if not isinstance(guild, dict):
            return self._serialize_live_guild(guild)
        return {
            'id': str(guild.get('id')),
            'name': guild.get('name'),
            'description': guild.get('description'),
            'icon': guild.get('icon'),
            'banner': guild.get('banner'),
            'owner_id': (
                str(guild.get('owner_id'))
                if guild.get('owner_id') else None
            ),
            'owner_name': guild.get('owner_name'),
            'owner_avatar': guild.get('owner_avatar'),
            'created_at': guild.get('created_at'),
            'verification_level': str(
                guild.get('verification_level', 'unknown')
            ),
            'preferred_locale': str(
                guild.get('preferred_locale', 'unknown')
            ),
            'premium_tier': int(guild.get('premium_tier') or 0),
            'premium_subscription_count': int(
                guild.get('premium_subscription_count') or 0
            ),
            'features': list(guild.get('features') or []),
            'member_count': int(guild.get('member_count') or 0),
            'channel_count': int(guild.get('channel_count') or 0),
            'text_channel_count': int(guild.get('text_channel_count') or 0),
            'voice_channel_count': int(guild.get('voice_channel_count') or 0),
            'category_count': int(guild.get('category_count') or 0),
            'stage_channel_count': int(guild.get('stage_channel_count') or 0),
            'forum_channel_count': int(guild.get('forum_channel_count') or 0),
            'role_count': int(guild.get('role_count') or 0),
            'emoji_count': int(guild.get('emoji_count') or 0),
            'sticker_count': int(guild.get('sticker_count') or 0),
        }

    def _serialize_live_guild(self, guild):
        """Live discord.py Guild -> the same shape as the dict path."""
        members = list(getattr(guild, "members", []) or [])
        channels = list(getattr(guild, "channels", []) or [])
        roles = list(getattr(guild, "roles", []) or [])
        text_channels = [
            c for c in channels if isinstance(c, discord.TextChannel)
        ]
        voice_channels = [
            c for c in channels if isinstance(c, discord.VoiceChannel)
        ]
        categories = [
            c for c in channels if isinstance(c, discord.CategoryChannel)
        ]
        stage_channels = [
            c for c in channels if isinstance(c, discord.StageChannel)
        ]
        forum_channels = [
            c for c in channels if isinstance(c, discord.ForumChannel)
        ]
        owner_name = None
        owner_avatar = None
        try:
            if guild.owner:
                owner_name = guild.owner.display_name
                owner_avatar = self._asset_url(guild.owner.display_avatar)
        except Exception:
            pass
        return {
            "id": str(guild.id),
            "name": guild.name,
            "description": getattr(guild, "description", None),
            "icon": self._asset_url(getattr(guild, "icon", None)),
            "banner": self._asset_url(getattr(guild, "banner", None)),
            "owner_id": (
                str(guild.owner_id)
                if getattr(guild, "owner_id", None) else None
            ),
            "owner_name": owner_name,
            "owner_avatar": owner_avatar,
            "created_at": (
                guild.created_at.isoformat()
                if getattr(guild, "created_at", None) else None
            ),
            "verification_level": str(
                getattr(guild, "verification_level", "unknown")
            ),
            "preferred_locale": str(
                getattr(guild, "preferred_locale", "unknown")
            ),
            "premium_tier": int(getattr(guild, "premium_tier", 0) or 0),
            "premium_subscription_count": int(
                getattr(guild, "premium_subscription_count", 0) or 0
            ),
            "features": list(getattr(guild, "features", []) or []),
            "member_count": int(
                getattr(guild, "member_count", 0) or len(members) or 0
            ),
            "channel_count": len(channels),
            "text_channel_count": len(text_channels),
            "voice_channel_count": len(voice_channels),
            "category_count": len(categories),
            "stage_channel_count": len(stage_channels),
            "forum_channel_count": len(forum_channels),
            "role_count": len(roles),
            "emoji_count": len(getattr(guild, "emojis", []) or []),
            "sticker_count": len(getattr(guild, "stickers", []) or []),
        }

    def overview(self, guild_id):
        guild = self.get_guild(guild_id)
        return self.serialize_guild(guild) if guild else None

    def get_servers(self):
        if self._live:
            try:
                if not self.bot.is_ready():
                    return []
            except Exception:
                return []
            return [
                self.serialize_guild(guild) for guild in self.bot.guilds
            ]
        try:
            return [
                self.serialize_guild(guild)
                for guild in bridge.get_guilds()
            ]
        except BridgeUnavailable:
            return []

    def get_dashboard(self, guild_id):
        """The bot side computes the dashboard (its Logger-DB part reads
        message_log.db directly, as today). Returns the dashboard dict,
        or None when the guild is unknown / the bridge is down."""
        if self._live:
            return self._live_dashboard(guild_id)
        try:
            return bridge.get_guild_dashboard(guild_id)
        except BridgeUnavailable:
            return None

    def _live_dashboard(self, guild_id):
        """Dashboard computed from the live bot (bot-side bridge path).

        Same shape the website expects from the bridge; the Logger-DB
        part reads message_log.db directly (sync sqlite, which is why
        bridge_api runs this in asyncio.to_thread).
        """
        guild = self.get_guild(guild_id)
        if guild is None:
            return None

        members = list(guild.members)
        channels = list(guild.channels)
        roles = list(guild.roles)
        humans = [m for m in members if not m.bot]
        bots = [m for m in members if m.bot]
        online = sum(
            1 for m in members
            if str(getattr(m, "status", "offline")) == "online"
        )
        idle = sum(
            1 for m in members
            if str(getattr(m, "status", "offline")) == "idle"
        )
        dnd = sum(
            1 for m in members
            if str(getattr(m, "status", "offline"))
            in {"dnd", "do_not_disturb"}
        )
        offline = len(members) - online - idle - dnd
        text = [c for c in channels if isinstance(c, discord.TextChannel)]
        voice = [c for c in channels if isinstance(c, discord.VoiceChannel)]
        categories = [
            c for c in channels if isinstance(c, discord.CategoryChannel)
        ]
        stage = [c for c in channels if isinstance(c, discord.StageChannel)]
        forum = [c for c in channels if isinstance(c, discord.ForumChannel)]
        managed = [r for r in roles if r.managed]
        custom = [
            r for r in roles if not r.managed and r.name != "@everyone"
        ]
        admin_roles = [r for r in custom if r.permissions.administrator]
        # Real event data from the Logger events table.
        try:
            from web.services.logger_db import logger_db
            event_count = logger_db.count_events(guild_id)
            recent_events = logger_db.search_events(guild_id, limit=10)
        except Exception:
            event_count = 0
            recent_events = []
        member_count = int(getattr(guild, "member_count", 0) or len(members))
        return {
            "server": self.serialize_guild(guild),
            "members": {
                "count": member_count, "total": len(members),
                "humans": len(humans), "bots": len(bots),
                "online": online, "idle": idle, "dnd": dnd,
                "offline": max(0, offline),
            },
            "channels": {
                "count": len(channels), "total": len(channels),
                "categories": len(categories), "text": len(text),
                "voice": len(voice), "stage": len(stage),
                "forum": len(forum),
            },
            "roles": {
                "count": len(roles), "total": len(roles),
                "custom": len(custom), "managed": len(managed),
                "administrator": len(admin_roles),
            },
            "events": {"count": event_count, "total": event_count},
            "channel_list": [
                {"id": c.id, "name": c.name, "type": type(c).__name__}
                for c in channels
            ],
            "statistics": {
                "members": len(members), "humans": len(humans),
                "bots": len(bots), "online": online, "idle": idle,
                "dnd": dnd, "offline": max(0, offline),
                "channels": len(channels), "text_channels": len(text),
                "voice_channels": len(voice), "categories": len(categories),
                "roles": len(roles),
            },
            "recent_events": recent_events,
            "event_statistics": {"total": event_count},
            "bot": {
                "ready": bool(self.bot.is_ready()),
                "latency_ms": round(
                    float(getattr(self.bot, "latency", 0) or 0) * 1000, 2
                ),
            },
        }

    def get_statistics(self, guild_id):
        """Per-guild counts, same shape GuildService.get_guild_statistics
        returns. api.py called this before the split, but no
        ServerService ever defined it (pre-existing broken call site:
        AttributeError -> 500). Returns None when the guild is unknown
        / the bridge is down, so the route answers 404/503 as before."""
        guild = self.get_guild(guild_id)
        if guild is None:
            return None
        if not isinstance(guild, dict):
            guild = self.serialize_guild(guild)
        return {
            "members": int(guild.get("member_count") or 0),
            "channels": int(guild.get("channel_count") or 0),
            "text_channels": int(guild.get("text_channel_count") or 0),
            "voice_channels": int(guild.get("voice_channel_count") or 0),
            "categories": int(guild.get("category_count") or 0),
            "roles": int(guild.get("role_count") or 0),
            "emojis": int(guild.get("emoji_count") or 0),
            "stickers": int(guild.get("sticker_count") or 0),
        }
