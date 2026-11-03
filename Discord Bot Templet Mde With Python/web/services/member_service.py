"""Member data service -- bridge client (BRIDGE_CONTRACT.md section 6).

Same public interface and return shapes as before, but every read goes
through the bot-side bridge instead of the live bot object. The bridge
returns member dicts in the serialize_member() shape (plus
``timed_out_until`` and ``guild_permissions``); this module returns
those dicts as BridgeDicts, so unmigrated call sites can still use
``member.id`` / ``member.bot`` / ``member.status`` attribute access.

``serialize_member`` stays as the shape reference: it normalises a
bridge member dict, and still accepts a discord.py Member object for
any caller that still has one.
"""


from web.services import bridge
from web.services.bridge import BridgeDict, BridgeUnavailable, wrap


class MemberService:

    def __init__(self, bot=None):
        # Kept for call-site compat (MemberService(bot) / MemberService()).
        # The website passes no bot (bridge path); the bot-side bridge
        # passes the live bot (live path -- see DUAL MODE note in
        # server_service.py; before that fix the bridge's member search
        # called back into the bridge and hung).
        self.bot = bot

    @property
    def _live(self):
        """True when constructed with a live discord bot object."""
        return self.bot is not None and hasattr(self.bot, "get_guild")

    # ---------------------------------------------
    # GET GUILD
    # ---------------------------------------------

    def get_guild(self, guild_id):
        if self._live:
            if self.bot is None:
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

    # ---------------------------------------------
    # GET MEMBER
    # ---------------------------------------------

    def get_member(
        self,
        guild_id,
        user_id
    ):
        if self._live:
            guild = self.get_guild(guild_id)
            if guild is None:
                return None
            try:
                return guild.get_member(int(user_id))
            except (TypeError, ValueError):
                return None
        try:
            member = bridge.get_member(guild_id, user_id)
            return wrap(member) if member is not None else None
        except BridgeUnavailable:
            return None

    # ---------------------------------------------
    # GET ALL MEMBERS
    # ---------------------------------------------

    def get_members(
        self,
        guild_id,
        limit=None,
        after=None,
        q=None
    ):
        """All members of a guild (bridge dicts), paging through the
        bridge's 500-per-page cap. ``limit`` caps the total returned.
        Live path returns live Member objects (the bridge's member
        list handler pages them itself)."""
        if self._live:
            guild = self.get_guild(guild_id)
            if guild is None:
                return []
            members = list(guild.members)
            if q:
                q = str(q).lower()
                members = [
                    m for m in members
                    if q in (m.name or "").lower()
                    or q in (m.display_name or "").lower()
                    or q in (m.nick or "").lower()
                    or q in str(m.id)
                ]
            if limit is not None:
                members = members[:limit]
            return members
        members = []
        cursor = after
        try:
            while True:
                page = bridge.get_members(
                    guild_id, limit=500, after=cursor, q=q
                )
                batch = [wrap(m) for m in page.get("members") or []]
                members.extend(batch)
                if limit is not None and len(members) >= limit:
                    return members[:limit]
                cursor = page.get("next_after")
                if not cursor or not batch:
                    return members
        except BridgeUnavailable:
            return members

    # ---------------------------------------------
    # SERIALIZE MEMBER
    # ---------------------------------------------

    def serialize_member(
        self,
        member
    ):

        if member is None:
            return None

        # Bridge dict: normalise keys, keep the documented shape.
        if isinstance(member, dict):
            roles = []
            for role in member.get("roles") or []:
                if isinstance(role, dict):
                    roles.append({
                        "id": str(role.get("id")),
                        "name": role.get("name"),
                        "position": role.get("position"),
                        "color": role.get("color"),
                    })
            top_role = member.get("top_role")
            if isinstance(top_role, dict):
                top_role = {
                    "id": str(top_role.get("id")),
                    "name": top_role.get("name"),
                    "position": top_role.get("position"),
                }
            data = {
                "id": str(member.get("id")),
                "username": member.get("username"),
                "display_name": member.get("display_name"),
                "nickname": member.get("nickname"),
                "bot": bool(member.get("bot", False)),
                "status": member.get("status") or "offline",
                "avatar": member.get("avatar"),
                "created_at": member.get("created_at"),
                "joined_at": member.get("joined_at"),
                "roles": roles,
                "top_role": top_role,
                "permissions": list(member.get("permissions") or []),
            }
            # Bridge-only extras, passed through when present.
            if "timed_out_until" in member:
                data["timed_out_until"] = member.get("timed_out_until")
            if "guild_permissions" in member:
                data["guild_permissions"] = member.get("guild_permissions")
            return data

        # discord.py Member object (shape reference / leftover callers).
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

        if self._live:
            # Live path: filter the guild's members directly (same
            # match rule as the old local search).
            guild = self.get_guild(guild_id)
            if guild is None:
                return []
            if not query:
                return list(guild.members)
            query = str(query).lower()
            results = []
            for member in guild.members:
                if (
                    query in (member.name or "").lower()
                    or query in (member.display_name or "").lower()
                    or query in (member.nick or "").lower()
                    or query in str(member.id)
                ):
                    results.append(member)
            return results

        if not query:
            return self.get_members(guild_id)

        query = str(query)
        members = []
        cursor = None
        try:
            while True:
                page = bridge.get_members(
                    guild_id, limit=500, after=cursor, q=query
                )
                batch = [wrap(m) for m in page.get("members") or []]
                members.extend(batch)
                cursor = page.get("next_after")
                if not cursor or not batch:
                    return members
        except BridgeUnavailable:
            return members
