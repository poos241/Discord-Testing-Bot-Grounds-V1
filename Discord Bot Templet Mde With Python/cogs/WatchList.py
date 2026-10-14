"""Watch List system: keep an eye on specific users' messages.

Moderators add users to a per-server watch list; every message a watched
user sends is mirrored to a configured log channel. All state lives in
``watchlist_data.json`` (via config.load_json / save_json).

This system is intentionally separate from the main Logger.
"""
import re
from datetime import datetime, timezone

import discord
from discord.ext import commands

try:
    from config import load_json, save_json, extra_help
    _HAS_CONFIG = True
except ImportError:  # cog used outside this project
    _HAS_CONFIG = False

    def load_json(filename):  # type: ignore
        import json, os
        path = os.path.join("data", filename)
        if not os.path.exists(path):
            return {}
        try:
            with open(path) as f:
                return json.load(f) or {}
        except Exception:
            return {}

    def save_json(filename, data):  # type: ignore
        import json, os
        os.makedirs("data", exist_ok=True)
        with open(os.path.join("data", filename), "w") as f:
            json.dump(data, f, indent=2)

    def extra_help(text):  # type: ignore
        def deco(fn):
            return fn
        return deco


WATCHLIST_FILE = "watchlist_data.json"
MAX_MESSAGE_LENGTH = 4000
MAX_ATTACHMENTS = 10
_CHUNK_LIMIT = 1000  # stay under Discord's 1024-char field limit
_MENTION_RE = re.compile(r"<@!?(\d+)>")

ORANGE = discord.Color.orange()


def watch_admin():
    """commands.check: allow Manage Server or Administrator."""
    async def predicate(ctx):
        perms = ctx.author.guild_permissions
        if perms.administrator or perms.manage_guild:
            return True
        await ctx.respond(
            "❌ You need **Manage Server** or **Administrator** to use this command.",
            ephemeral=True,
        )
        return False
    return commands.check(predicate)


class WatchList(commands.Cog):
    """Per-server watch list with message logging."""

    def __init__(self, bot):
        self.bot = bot
        self.db = self._load_db()

    # ----- storage -----

    def _load_db(self):
        try:
            data = load_json(WATCHLIST_FILE)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            print(f"[WatchList] Could not load {WATCHLIST_FILE}: {e}")
            return {}

    def _save_db(self):
        try:
            save_json(WATCHLIST_FILE, self.db)
        except Exception as e:
            print(f"[WatchList] Could not save {WATCHLIST_FILE}: {e}")

    def _guild_data(self, guild_id):
        """Get (creating if needed) this guild's watch-list data."""
        gid = str(guild_id)
        data = self.db.get(gid)
        if not isinstance(data, dict):
            data = {}
            self.db[gid] = data
        data.setdefault("log_channel_id", None)
        data.setdefault("users", {})
        return data

    def _get_watched_user(self, guild_id, user_id):
        return self._guild_data(guild_id)["users"].get(str(user_id))

    def _is_watched(self, guild_id, user_id):
        return str(user_id) in self._guild_data(guild_id)["users"]

    def _user_record(self, member, added_by):
        """Build the stored dict for a newly watched user."""
        now = datetime.now(timezone.utc).isoformat()
        return {
            "user_id": str(member.id),
            "username": member.name,
            "display_name": member.display_name,
            "added_by": str(added_by.id),
            "added_by_name": str(added_by),
            "added_at": now,
        }

    # ----- shared parsing / lookup -----

    @staticmethod
    def _parse_user_id(raw):
        """Parse a user ID from raw input (ID or mention). Returns int or None."""
        if not raw:
            return None
        raw = raw.strip()
        m = _MENTION_RE.fullmatch(raw)
        if m:
            raw = m.group(1)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return None

    async def _resolve_member(self, guild, user_id):
        """Get a Member from cache or API. Returns (member, error_message)."""
        member = guild.get_member(user_id)
        if member is not None:
            return member, None
        try:
            return await guild.fetch_member(user_id), None
        except discord.NotFound:
            return None, "❌ I couldn't find that user in this server."
        except discord.Forbidden:
            return None, "❌ I don't have permission to look up that member."
        except Exception as e:
            return None, f"❌ Failed to look up that user: `{e}`"

    @staticmethod
    def _chunk_lines(lines, limit=_CHUNK_LIMIT):
        """Split lines into chunks that fit in embed fields."""
        chunks, current = [], []
        for line in lines:
            candidate = "\n\n".join(current + [line])
            if len(candidate) > limit and current:
                chunks.append("\n\n".join(current))
                current = [line]
            else:
                current.append(line)
        if current:
            chunks.append("\n\n".join(current))
        return chunks

    def _get_log_channel(self, guild):
        if guild is None:
            return None
        channel_id = self._guild_data(guild.id).get("log_channel_id")
        if not channel_id:
            return None
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return None
        return guild.get_channel(channel_id) or self.bot.get_channel(channel_id)

    # ----- embeds -----

    def _base_log_embed(self, message):
        """Build the message-log embed for a watched user's message."""
        author = message.author
        ts = int(message.created_at.timestamp())
        embed = discord.Embed(
            title="👁️ Watch List Message",
            color=ORANGE,
            timestamp=message.created_at,
        )
        embed.set_author(
            name=f"{author.display_name} (@{author.name})",
            icon_url=author.display_avatar.url,
        )
        embed.add_field(
            name="User", value=f"{author.mention}\n`{author.id}`", inline=True
        )
        channel = message.channel
        embed.add_field(
            name="Channel",
            value=channel.mention if hasattr(channel, "mention") else f"`{channel.name}`",
            inline=True,
        )
        embed.add_field(
            name="Time", value=f"<t:{ts}:F>\n<t:{ts}:R>", inline=True
        )

        content = message.content.strip() or "*No text content*"
        if len(content) > MAX_MESSAGE_LENGTH:
            content = content[:MAX_MESSAGE_LENGTH - 20] + "\n\n... *(message truncated)*"
        embed.add_field(name="Message", value=content, inline=False)
        embed.add_field(
            name="Message Link", value=f"[Jump to Message]({message.jump_url})", inline=False
        )
        embed.set_thumbnail(url=author.display_avatar.url)
        return embed

    def _add_attachment_fields(self, embed, message):
        attachments = list(message.attachments)
        if not attachments:
            return
        lines, image_url = [], None
        for a in attachments[:MAX_ATTACHMENTS]:
            lines.append(f"[{a.filename}]({a.url})")
            ctype = str(getattr(a, "content_type", "") or "").lower()
            if image_url is None and (
                ctype.startswith("image/")
                or a.filename.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"))
            ):
                image_url = a.url
        if len(attachments) > MAX_ATTACHMENTS:
            lines.append(f"*...and {len(attachments) - MAX_ATTACHMENTS} more*")
        embed.add_field(
            name=f"📎 Attachments ({len(attachments)})",
            value="\n".join(lines),
            inline=False,
        )
        if image_url:
            embed.set_image(url=image_url)

    def _add_sticker_fields(self, embed, message):
        stickers = getattr(message, "stickers", None)
        if not stickers:
            return
        lines = [f"• `{getattr(s, 'name', 'Unknown Sticker')}`" for s in stickers[:MAX_ATTACHMENTS]]
        if len(stickers) > MAX_ATTACHMENTS:
            lines.append(f"*...and {len(stickers) - MAX_ATTACHMENTS} more*")
        embed.add_field(
            name=f"🎨 Stickers ({len(stickers)})",
            value="\n".join(lines),
            inline=False,
        )

    def _added_embed(self, member, added_by):
        """Confirmation embed shared by /watch_add and /watch_add_id."""
        embed = discord.Embed(
            title="👁️ User Added to Watch List",
            color=ORANGE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(
            name="User",
            value=f"{member.mention}\n`@{member.name}`\n`{member.id}`",
            inline=True,
        )
        embed.add_field(name="Added By", value=added_by.mention, inline=True)
        return embed

    def _watched_line(self, guild, user_id, data):
        """One display line for a watched user (member or cached data)."""
        member = guild.get_member(int(user_id)) if user_id.isdigit() else None
        if member:
            return f"• {member.mention} — {member.display_name} (`@{member.name}`)\n  ID: `{user_id}`"
        name = data.get("display_name", "Unknown User")
        username = data.get("username", "Unknown")
        return f"• <@{user_id}> — {name} (`@{username}`)\n  ID: `{user_id}`"

    # ----- listeners -----

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.guild is None or message.author.bot:
            return
        guild = message.guild
        if not self._is_watched(guild.id, message.author.id):
            return
        log_channel = self._get_log_channel(guild)
        if log_channel is None or message.channel.id == getattr(log_channel, "id", None):
            return
        try:
            embed = self._base_log_embed(message)
            self._add_attachment_fields(embed, message)
            self._add_sticker_fields(embed, message)
            embed.set_footer(text=f"Watch List • User ID: {message.author.id}")
            await log_channel.send(
                embed=embed, allowed_mentions=discord.AllowedMentions.none()
            )
        except (discord.Forbidden, discord.NotFound) as e:
            print(f"[WatchList] Cannot log to #{getattr(log_channel, 'name', '?')} "
                  f"in {guild.name}: {e}")
        except Exception as e:
            print(f"[WatchList] Error logging message: {e}")

    # ----- commands -----

    @discord.slash_command(name="watch_add", description="Add a user to the watch list.")
    @extra_help("Add a user to the watch list. Their messages will be logged to the watch-list channel. Admins only (Manage Server or Administrator).")
    @watch_admin()
    async def watch_add(self, ctx: discord.ApplicationContext,
                        user: discord.Option(discord.Member, "User to watch")):  # type: ignore
        """Add a user via Discord's native member picker."""
        guild_data = self._guild_data(ctx.guild.id)
        if str(user.id) in guild_data["users"]:
            await ctx.respond(f"⚠️ {user.mention} is already on the watch list.",
                              ephemeral=True)
            return
        guild_data["users"][str(user.id)] = self._user_record(user, ctx.author)
        self._save_db()
        await ctx.respond(embed=self._added_embed(user, ctx.author), ephemeral=True)

    @discord.slash_command(name="watch_remove", description="Remove a user from the watch list.")
    @extra_help("Remove a user from the watch list. Their messages stop being logged. Admins only.")
    @watch_admin()
    async def watch_remove(self, ctx: discord.ApplicationContext,
                           user: discord.Option(discord.Member, "User to remove")):  # type: ignore
        """Remove a user via the member picker."""
        guild_data = self._guild_data(ctx.guild.id)
        if str(user.id) not in guild_data["users"]:
            await ctx.respond(f"❌ {user.mention} is not on the watch list.",
                              ephemeral=True)
            return
        del guild_data["users"][str(user.id)]
        self._save_db()
        await ctx.respond(f"🗑️ Removed {user.mention} from the watch list.",
                          ephemeral=True)

    @discord.slash_command(name="watch_add_id", description="Add a user to the watch list by ID.")
    @extra_help("Add a user to the watch list using their Discord ID (or mention). Useful when they aren't easy to find in the member picker. Admins only.")
    @watch_admin()
    async def watch_add_id(self, ctx: discord.ApplicationContext,
                           user_id: discord.Option(str, "Discord user ID")):  # type: ignore
        """Add a user by raw ID."""
        numeric_id = self._parse_user_id(user_id)
        if numeric_id is None:
            await ctx.respond("❌ That doesn't look like a valid Discord user ID.",
                              ephemeral=True)
            return
        member, error = await self._resolve_member(ctx.guild, numeric_id)
        if error:
            await ctx.respond(error, ephemeral=True)
            return
        guild_data = self._guild_data(ctx.guild.id)
        if str(member.id) in guild_data["users"]:
            await ctx.respond(f"⚠️ {member.mention} is already on the watch list.",
                              ephemeral=True)
            return
        guild_data["users"][str(member.id)] = self._user_record(member, ctx.author)
        self._save_db()
        await ctx.respond(embed=self._added_embed(member, ctx.author), ephemeral=True)

    @discord.slash_command(name="watch_remove_id", description="Remove a user from the watch list by ID.")
    @extra_help("Remove a user from the watch list using their Discord ID. Admins only.")
    @watch_admin()
    async def watch_remove_id(self, ctx: discord.ApplicationContext,
                              user_id: discord.Option(str, "Discord user ID")):  # type: ignore
        """Remove a user by raw ID."""
        numeric_id = self._parse_user_id(user_id)
        if numeric_id is None:
            await ctx.respond("❌ That doesn't look like a valid Discord user ID.",
                              ephemeral=True)
            return
        guild_data = self._guild_data(ctx.guild.id)
        removed = guild_data["users"].pop(str(numeric_id), None)
        if removed is None:
            await ctx.respond(f"❌ User ID `{numeric_id}` is not on the watch list.",
                              ephemeral=True)
            return
        self._save_db()
        member = ctx.guild.get_member(numeric_id)
        display = member.mention if member else f"`{removed.get('display_name', 'Unknown User')}`"
        await ctx.respond(f"🗑️ Removed {display} from the watch list.\nID: `{numeric_id}`",
                          ephemeral=True)

    @discord.slash_command(name="watch_list", description="Show everyone on the watch list.")
    @extra_help("Show everyone currently on the watch list, with the log channel status. Admins only.")
    @watch_admin()
    async def watch_list(self, ctx: discord.ApplicationContext):
        """Show the current watch list."""
        guild_data = self._guild_data(ctx.guild.id)
        users = guild_data.get("users", {})
        if not users:
            await ctx.respond("👁️ The watch list is currently empty.", ephemeral=True)
            return
        embed = discord.Embed(
            title="👁️ Watch List",
            description=f"**{len(users)}** user(s) currently being watched.",
            color=ORANGE,
        )
        lines = [self._watched_line(ctx.guild, uid, data) for uid, data in users.items()]
        for i, chunk in enumerate(self._chunk_lines(lines)[:25]):
            embed.add_field(
                name="Watched Users" if i == 0 else "Watched Users (continued)",
                value=chunk,
                inline=False,
            )
        log_channel = self._get_log_channel(ctx.guild)
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "❌ Not configured",
            inline=False,
        )
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="watch_status", description="Show the watch-list system status.")
    @extra_help("Show watch-list status: user count, log channel, and logging state. Admins only.")
    @watch_admin()
    async def watch_status(self, ctx: discord.ApplicationContext):
        """Show system status."""
        guild_data = self._guild_data(ctx.guild.id)
        users = guild_data.get("users", {})
        log_channel = self._get_log_channel(ctx.guild)
        embed = discord.Embed(
            title="👁️ Watch List Status",
            color=ORANGE,
            timestamp=datetime.now(timezone.utc),
        )
        embed.add_field(name="Watched Users", value=f"`{len(users)}`", inline=True)
        embed.add_field(
            name="Log Channel",
            value=log_channel.mention if log_channel else "❌ Not configured",
            inline=True,
        )
        embed.add_field(
            name="Logging",
            value="🟢 Online" if log_channel else "🔴 Not configured",
            inline=True,
        )
        if users:
            lines = [self._watched_line(ctx.guild, uid, data) for uid, data in users.items()]
            for i, chunk in enumerate(self._chunk_lines(lines)[:25]):
                embed.add_field(
                    name="Watched Users" if i == 0 else f"Watched Users {i + 1}",
                    value=chunk,
                    inline=False,
                )
        else:
            embed.add_field(name="Watched Users",
                            value="No users are currently being watched.",
                            inline=False)
        embed.set_footer(text="Watch List • Separate from the main Logger")
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="watch_info", description="Show information about a watched user.")
    @extra_help("Show details about one watched user: who added them and when. Admins only.")
    @watch_admin()
    async def watch_info(self, ctx: discord.ApplicationContext,
                         user: discord.Option(discord.Member, "User to inspect")):  # type: ignore
        """Show information about one watched user."""
        data = self._get_watched_user(ctx.guild.id, user.id)
        if data is None:
            await ctx.respond(f"❌ {user.mention} is not on the watch list.",
                              ephemeral=True)
            return
        embed = discord.Embed(title="👁️ Watch List User Information", color=ORANGE)
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(
            name="User",
            value=f"{user.mention}\n`@{user.name}` • `{user.id}`",
            inline=False,
        )
        added_by_id = data.get("added_by")
        added_by = ctx.guild.get_member(int(added_by_id)) if added_by_id else None
        embed.add_field(
            name="Added By",
            value=f"{added_by.mention}\n`{added_by.id}`" if added_by else (
                f"<@{added_by_id}>\n`{added_by_id}`" if added_by_id else "Unknown"),
            inline=True,
        )
        added_at = data.get("added_at")
        if added_at:
            try:
                ts = int(datetime.fromisoformat(
                    added_at.replace("Z", "+00:00")).timestamp())
                added_value = f"<t:{ts}:F>\n<t:{ts}:R>"
            except Exception:
                added_value = f"`{added_at}`"
        else:
            added_value = "Unknown"
        embed.add_field(name="Added", value=added_value, inline=True)
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="watch_set_channel",
                           description="Set the watch-list log channel.")
    @extra_help("Set the channel where watched users' messages are logged. Admins only.")
    @watch_admin()
    async def watch_set_channel(self, ctx: discord.ApplicationContext,
                                channel: discord.Option(discord.TextChannel, "Channel for watch-list logs")):  # type: ignore
        """Set the logging channel."""
        self._guild_data(ctx.guild.id)["log_channel_id"] = str(channel.id)
        self._save_db()
        embed = discord.Embed(
            title="👁️ Watch List Log Channel Updated",
            color=discord.Color.green(),
        )
        embed.add_field(name="Log Channel", value=channel.mention, inline=True)
        embed.add_field(name="Status", value="🟢 Enabled", inline=True)
        await ctx.respond(embed=embed, ephemeral=True)

    @discord.slash_command(name="watch_clear", description="Remove everyone from the watch list.")
    @extra_help("Remove every user from the watch list (with confirmation). Already-sent logs are kept. Admins only.")
    @watch_admin()
    async def watch_clear(self, ctx: discord.ApplicationContext):
        """Clear the entire watch list after confirmation."""
        guild_data = self._guild_data(ctx.guild.id)
        users = guild_data.get("users", {})
        if not users:
            await ctx.respond("👁️ The watch list is already empty.", ephemeral=True)
            return

        class ConfirmView(discord.ui.View):
            def __init__(self, cog, author_id):
                super().__init__(timeout=30)
                self.cog = cog
                self.author_id = author_id

            async def interaction_check(self, interaction: discord.Interaction):
                if interaction.user.id != self.author_id:
                    await interaction.response.send_message(
                        "❌ You cannot use this confirmation.", ephemeral=True)
                    return False
                return True

            @discord.ui.button(label="Clear Watch List",
                               style=discord.ButtonStyle.danger, emoji="🗑️")
            async def confirm(self, button, interaction):
                data = self.cog._guild_data(interaction.guild.id)
                count = len(data.get("users", {}))
                data["users"] = {}
                self.cog._save_db()
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(
                    content=f"🗑️ Cleared **{count}** user(s) from the watch list.",
                    embed=None, view=self)
                self.stop()

            @discord.ui.button(label="Cancel",
                               style=discord.ButtonStyle.secondary, emoji="❌")
            async def cancel(self, button, interaction):
                for child in self.children:
                    child.disabled = True
                await interaction.response.edit_message(
                    content="❌ Watch-list clear cancelled.", embed=None, view=self)
                self.stop()

            async def on_timeout(self):
                for child in self.children:
                    child.disabled = True

        embed = discord.Embed(
            title="⚠️ Clear Watch List",
            description=(f"This will remove **{len(users)}** user(s) from the watch list.\n\n"
                         "This does **not** delete message logs already sent to Discord.\n\n"
                         "Are you sure?"),
            color=discord.Color.red(),
        )
        await ctx.respond(embed=embed,
                          view=ConfirmView(self, ctx.author.id),
                          ephemeral=True)

    @commands.Cog.listener()
    async def on_application_command_error(self, ctx, error):
        """Keep watch-list command errors from becoming unhandled task errors."""
        try:
            name = getattr(getattr(ctx, "command", None), "name", "")
            if not str(name).startswith("watch_"):
                return
        except Exception:
            return
        print(f"[WatchList] Command error: {error}")
        try:
            msg = "❌ Something went wrong while running that watch-list command."
            if ctx.response.is_done():
                await ctx.followup.send(msg, ephemeral=True)
            else:
                await ctx.respond(msg, ephemeral=True)
        except Exception:
            pass


def setup(bot):
    bot.add_cog(WatchList(bot))
