import discord
from discord.ext import commands
from datetime import datetime, timezone
from pathlib import Path




WATCHLIST_FILE = "watchlist_data.json"


MAX_MESSAGE_LENGTH = 4000

MAX_ATTACHMENTS = 10


class WatchList(commands.Cog):
    """
    Separate Discord Watch List system.

    This system does NOT use the existing Logger system.

    Features:
        /watch_add
        /watch_remove
        /watch_add_id
        /watch_remove_id
        /watch_list
        /watch_status
        /watch_info
        /watch_set_channel
        /watch_clear
    """

    def __init__(self, bot):
        self.bot = bot
        self.db = self._load_db()

  

    def _load_db(self):
        """
        Load watchlist_data.json.

        Uses the project's config.py helpers if available.
        Falls back to a normal JSON loader if necessary.
        """

        try:
            from config import load_json

            data = load_json(WATCHLIST_FILE)

            if not isinstance(data, dict):
                return {}

            return data

        except Exception as e:
            print(
                f"[WatchList] Could not load {WATCHLIST_FILE}: {e}"
            )
            return {}

    def _save_db(self):
        """
        Save watchlist_data.json.
        """

        try:
            from config import save_json

            save_json(WATCHLIST_FILE, self.db)

        except Exception as e:
            print(
                f"[WatchList] Could not save {WATCHLIST_FILE}: {e}"
            )

    def _guild_data(self, guild_id: int):
        """
        Get/create the watch-list data for a guild.
        """

        guild_id = str(guild_id)

        if guild_id not in self.db:
            self.db[guild_id] = {
                "log_channel_id": None,
                "users": {}
            }

        if not isinstance(self.db[guild_id], dict):
            self.db[guild_id] = {
                "log_channel_id": None,
                "users": {}
            }

        if "log_channel_id" not in self.db[guild_id]:
            self.db[guild_id]["log_channel_id"] = None

        if "users" not in self.db[guild_id]:
            self.db[guild_id]["users"] = {}

        return self.db[guild_id]

  

    def _get_watched_user(self, guild_id: int, user_id: int):
        """
        Return stored watch-list information for a user.
        """

        guild_data = self._guild_data(guild_id)

        return guild_data["users"].get(str(user_id))

    def _is_watched(self, guild_id: int, user_id: int):
        """
        Check whether a user is currently being watched.
        """

        guild_data = self._guild_data(guild_id)

        return str(user_id) in guild_data["users"]

    def _member_display_name(self, member):
        """
        Safely get a member's display name.
        """

        if member is None:
            return "Unknown User"

        try:
            return member.display_name
        except Exception:
            pass

        try:
            return member.name
        except Exception:
            return "Unknown User"

    def _member_username(self, member):
        """
        Safely get a member's username.
        """

        if member is None:
            return "Unknown"

        try:
            return member.name
        except Exception:
            return "Unknown"

    def _member_avatar_url(self, member):
        """
        Safely get avatar URL.
        """

        if member is None:
            return None

        try:
            return member.display_avatar.url
        except Exception:
            pass

        try:
            return member.avatar.url
        except Exception:
            return None



    def _get_log_channel(self, guild):
        """
        Get the configured watch-list log channel.
        """

        if guild is None:
            return None

        guild_data = self._guild_data(guild.id)

        channel_id = guild_data.get("log_channel_id")

        if not channel_id:
            return None

        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return None

        channel = guild.get_channel(channel_id)

        if channel is not None:
            return channel

        # Try the bot cache as a fallback.
        try:
            channel = self.bot.get_channel(channel_id)
        except Exception:
            channel = None

        return channel



    async def _check_admin(self, ctx):
        """
        Check that the person using the command has
        Manage Server or Administrator.

        This is intentionally handled internally so the
        watch-list commands don't depend on the existing
        Logger system.
        """

        if ctx.guild is None:
            await ctx.respond(
                "❌ This command can only be used inside a server.",
                ephemeral=True
            )
            return False

        try:
            member = ctx.author

            if member.guild_permissions.administrator:
                return True

            if member.guild_permissions.manage_guild:
                return True

        except Exception:
            pass

        await ctx.respond(
            "❌ You need **Manage Server** or **Administrator** permission to use this command.",
            ephemeral=True
        )

        return False


    def _base_log_embed(self, message, watched_data=None):
        """
        Create the base watch-list message log embed.
        """

        author = message.author

        embed = discord.Embed(
            title="👁️ Watch List Message",
            color=discord.Color.orange(),
            timestamp=message.created_at
        )

        display_name = self._member_display_name(author)
        username = self._member_username(author)

        embed.set_author(
            name=f"{display_name} (@{username})",
            icon_url=self._member_avatar_url(author)
            or discord.Embed.Empty
        )

        embed.add_field(
            name="User",
            value=f"{author.mention}\n`{author.id}`",
            inline=True
        )

        embed.add_field(
            name="Channel",
            value=message.channel.mention
            if hasattr(message.channel, "mention")
            else f"`{message.channel.name}`",
            inline=True
        )

        embed.add_field(
            name="Time",
            value=f"<t:{int(message.created_at.timestamp())}:F>\n"
                  f"<t:{int(message.created_at.timestamp())}:R>",
            inline=True
        )

    

        content = message.content.strip()

        if not content:
            content = "*No text content*"

        if len(content) > MAX_MESSAGE_LENGTH:
            content = (
                content[:MAX_MESSAGE_LENGTH - 20]
                + "\n\n... *(message truncated)*"
            )

        embed.add_field(
            name="Message",
            value=content,
            inline=False
        )



        try:
            embed.add_field(
                name="Message Link",
                value=f"[Jump to Message]({message.jump_url})",
                inline=False
            )
        except Exception:
            pass

 

        avatar_url = self._member_avatar_url(author)

        if avatar_url:
            try:
                embed.set_thumbnail(url=avatar_url)
            except Exception:
                pass

        return embed

    def _add_attachment_fields(self, embed, message):
        """
        Add attachment information and images.
        """

        attachments = list(message.attachments)

        if not attachments:
            return

        attachment_lines = []

        image_url = None

        for attachment in attachments[:MAX_ATTACHMENTS]:

            filename = attachment.filename
            url = attachment.url

            attachment_lines.append(
                f"[{filename}]({url})"
            )


            content_type = str(
                getattr(attachment, "content_type", "") or ""
            ).lower()

            filename_lower = filename.lower()

            is_image = (
                content_type.startswith("image/")
                or filename_lower.endswith((
                    ".png",
                    ".jpg",
                    ".jpeg",
                    ".gif",
                    ".webp",
                    ".bmp"
                ))
            )

            if is_image and image_url is None:
                image_url = url

        if len(attachments) > MAX_ATTACHMENTS:
            attachment_lines.append(
                f"*...and {len(attachments) - MAX_ATTACHMENTS} more attachment(s)*"
            )

        embed.add_field(
            name=f"📎 Attachments ({len(attachments)})",
            value="\n".join(attachment_lines),
            inline=False
        )


        if image_url:
            try:
                embed.set_image(url=image_url)
            except Exception:
                pass

    def _add_sticker_fields(self, embed, message):
        """
        Add sticker information.
        """

        stickers = getattr(message, "stickers", None)

        if not stickers:
            return

        sticker_lines = []

        for sticker in stickers[:MAX_ATTACHMENTS]:

            sticker_name = getattr(
                sticker,
                "name",
                "Unknown Sticker"
            )

            sticker_lines.append(
                f"• `{sticker_name}`"
            )

        if len(stickers) > MAX_ATTACHMENTS:
            sticker_lines.append(
                f"*...and {len(stickers) - MAX_ATTACHMENTS} more sticker(s)*"
            )

        embed.add_field(
            name=f"🎨 Stickers ({len(stickers)})",
            value="\n".join(sticker_lines),
            inline=False
        )

 

    @commands.Cog.listener()
    async def on_message(self, message):
        """
        Watch messages from watched users.
        """

        if message.guild is None:
            return

        if message.author.bot:
            return

        guild = message.guild


        if not self._is_watched(
            guild.id,
            message.author.id
        ):
            return

        log_channel = self._get_log_channel(guild)

        if log_channel is None:
            return

        if message.channel.id == getattr(
            log_channel,
            "id",
            None
        ):
            return

        try:
            embed = self._base_log_embed(
                message,
                self._get_watched_user(
                    guild.id,
                    message.author.id
                )
            )

            self._add_attachment_fields(
                embed,
                message
            )

            self._add_sticker_fields(
                embed,
                message
            )

            embed.set_footer(
                text=f"Watch List • User ID: {message.author.id}"
            )

            await log_channel.send(
                embed=embed,
                allowed_mentions=discord.AllowedMentions.none()
            )

        except discord.Forbidden:
            print(
                f"[WatchList] Missing permission to send to "
                f"#{getattr(log_channel, 'name', 'unknown')} "
                f"in {guild.name}"
            )

        except discord.NotFound:
            print(
                f"[WatchList] Watch-list log channel no longer exists "
                f"in {guild.name}"
            )

        except Exception as e:
            print(
                f"[WatchList] Error logging message: {e}"
            )

    @discord.slash_command(name="watch_add", description="Add a Discord user to the watch list.")
    async def watch_add(self, ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "Discord user to watch") ): # type: ignore
        """
        Add a user to the watch list.

        IMPORTANT:
        This uses Discord's native Member selector.

        Discord handles the name search instead of us trying
        to recreate Discord's autocomplete system.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(ctx.guild.id)

        user_id = str(user.id)

        # Already watched.
        if user_id in guild_data["users"]:

            await ctx.respond(
                f"⚠️ {user.mention} is already on the watch list.",
                ephemeral=True
            )

            return

        now = datetime.now(timezone.utc).isoformat()

        guild_data["users"][user_id] = {
            "user_id": user_id,
            "username": self._member_username(user),
            "display_name": self._member_display_name(user),
            "added_by": str(ctx.author.id),
            "added_by_name": str(ctx.author),
            "added_at": now
        }

        self._save_db()

        embed = discord.Embed(
            title="👁️ User Added to Watch List",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_thumbnail(
            url=self._member_avatar_url(user)
        )

        embed.add_field(
            name="User",
            value=f"{user.mention}\n"
                  f"**Username:** `{user.name}`\n"
                  f"**Display Name:** `{user.display_name}`",
            inline=False
        )

        embed.add_field(
            name="Discord ID",
            value=f"`{user.id}`",
            inline=True
        )

        embed.add_field(
            name="Added By",
            value=ctx.author.mention,
            inline=True
        )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    @discord.slash_command(name="watch_remove", description="Remove a Discord user from the watch list.")
    async def watch_remove(self, ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "Discord user to remove") ): # type: ignore
        """
        Remove a user from the watch list.

        Uses Discord's native Member selector.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(ctx.guild.id)

        user_id = str(user.id)

        if user_id not in guild_data["users"]:

            await ctx.respond(
                f"❌ {user.mention} is not currently on the watch list.",
                ephemeral=True
            )

            return

        removed_data = guild_data["users"].pop(
            user_id
        )

        self._save_db()

        embed = discord.Embed(
            title="🗑️ User Removed From Watch List",
            color=discord.Color.red(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.set_thumbnail(
            url=self._member_avatar_url(user)
        )

        embed.add_field(
            name="User",
            value=f"{user.mention}\n"
                  f"**Username:** `{user.name}`\n"
                  f"**Display Name:** `{user.display_name}`",
            inline=False
        )

        embed.add_field(
            name="Discord ID",
            value=f"`{user.id}`",
            inline=True
        )

        embed.add_field(
            name="Removed By",
            value=ctx.author.mention,
            inline=True
        )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    

    @discord.slash_command(name="watch_add_id", description="Add a user to the watch list using their Discord ID.")
    async def watch_add_id(self, ctx: discord.ApplicationContext, user_id: discord.Option(str, "Discord user ID") ): # type: ignore
        """
        Add a user by raw Discord ID.

        This is useful if the user isn't easy to find in
        Discord's native member picker.
        """

        if not await self._check_admin(ctx):
            return

        try:
            numeric_id = int(
                user_id.strip()
                .replace("<@", "")
                .replace("!", "")
                .replace(">", "")
            )

        except (TypeError, ValueError):

            await ctx.respond(
                "❌ That doesn't look like a valid Discord user ID.",
                ephemeral=True
            )

            return

        guild = ctx.guild

        member = guild.get_member(numeric_id)

        if member is None:

            try:
                member = await guild.fetch_member(
                    numeric_id
                )

            except discord.NotFound:

                await ctx.respond(
                    "❌ I couldn't find that user in this server.",
                    ephemeral=True
                )

                return

            except discord.Forbidden:

                await ctx.respond(
                    "❌ I don't have permission to look up that member.",
                    ephemeral=True
                )

                return

            except Exception as e:

                await ctx.respond(
                    f"❌ Failed to look up that user: `{e}`",
                    ephemeral=True
                )

                return

        guild_data = self._guild_data(guild.id)

        user_id_string = str(member.id)

        if user_id_string in guild_data["users"]:

            await ctx.respond(
                f"⚠️ {member.mention} is already on the watch list.",
                ephemeral=True
            )

            return

        now = datetime.now(timezone.utc).isoformat()

        guild_data["users"][user_id_string] = {
            "user_id": user_id_string,
            "username": self._member_username(member),
            "display_name": self._member_display_name(member),
            "added_by": str(ctx.author.id),
            "added_by_name": str(ctx.author),
            "added_at": now
        }

        self._save_db()

        await ctx.respond(
            f"👁️ Added {member.mention} to the watch list.\n"
            f"Discord ID: `{member.id}`",
            ephemeral=True
        )

  

    @discord.slash_command(name="watch_remove_id", description="Remove a user from the watch list using their Discord ID.")
    async def watch_remove_id(self, ctx: discord.ApplicationContext, user_id: discord.Option(str, "Discord user ID") ): # type: ignore
        """
        Remove a user by raw Discord ID.
        """

        if not await self._check_admin(ctx):
            return

        try:
            numeric_id = int(
                user_id.strip()
                .replace("<@", "")
                .replace("!", "")
                .replace(">", "")
            )

        except (TypeError, ValueError):

            await ctx.respond(
                "❌ That doesn't look like a valid Discord user ID.",
                ephemeral=True
            )

            return

        guild_data = self._guild_data(ctx.guild.id)

        user_id_string = str(numeric_id)

        if user_id_string not in guild_data["users"]:

            await ctx.respond(
                f"❌ User ID `{numeric_id}` is not on the watch list.",
                ephemeral=True
            )

            return

        removed = guild_data["users"].pop(
            user_id_string
        )

        self._save_db()

        member = ctx.guild.get_member(
            numeric_id
        )

        if member:

            display = member.mention

        else:

            display = (
                f"`{removed.get('display_name', 'Unknown User')}`"
            )

        await ctx.respond(
            f"🗑️ Removed {display} from the watch list.\n"
            f"Discord ID: `{numeric_id}`",
            ephemeral=True
        )


    @discord.slash_command(name="watch_list", description="Show everyone currently on the watch list.")
    async def watch_list(self, ctx: discord.ApplicationContext):
        """
        Show the current watch list.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(
            ctx.guild.id
        )

        users = guild_data.get(
            "users",
            {}
        )

        if not users:

            await ctx.respond(
                "👁️ The watch list is currently empty.",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="👁️ Watch List",
            description=(
                f"There are **{len(users)}** "
                f"user(s) currently being watched."
            ),
            color=discord.Color.orange()
        )

        lines = []

        for user_id, data in users.items():

            member = ctx.guild.get_member(
                int(user_id)
            )

            if member:

                name = (
                    f"{member.display_name} "
                    f"(`@{member.name}`)"
                )

                mention = member.mention

            else:

                name = (
                    f"{data.get('display_name', 'Unknown User')} "
                    f"(`@{data.get('username', 'Unknown')}`)"
                )

                mention = f"<@{user_id}>"

            lines.append(
                f"• {mention} — {name}\n"
                f"  ID: `{user_id}`"
            )

       
        chunks = []

        current_chunk = []

        for line in lines:

            test_chunk = "\n\n".join(
                current_chunk + [line]
            )

            if len(test_chunk) > 1000:

                if current_chunk:
                    chunks.append(
                        "\n\n".join(current_chunk)
                    )

                current_chunk = [line]

            else:

                current_chunk.append(line)

        if current_chunk:
            chunks.append(
                "\n\n".join(current_chunk)
            )

        for index, chunk in enumerate(chunks[:25]):

            embed.add_field(
                name=(
                    "Watched Users"
                    if index == 0
                    else "Watched Users (continued)"
                ),
                value=chunk,
                inline=False
            )

        log_channel = self._get_log_channel(
            ctx.guild
        )

        if log_channel:

            embed.add_field(
                name="Log Channel",
                value=log_channel.mention,
                inline=False
            )

        else:

            embed.add_field(
                name="Log Channel",
                value="❌ Not configured",
                inline=False
            )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    @discord.slash_command(name="watch_status", description="Show the watch-list system status.")
    async def watch_status(self, ctx: discord.ApplicationContext):
        """
        Show complete watch-list status.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(
            ctx.guild.id
        )

        users = guild_data.get(
            "users",
            {}
        )

        log_channel = self._get_log_channel(
            ctx.guild
        )

        embed = discord.Embed(
            title="👁️ Watch List Status",
            color=discord.Color.orange(),
            timestamp=datetime.now(timezone.utc)
        )

        embed.add_field(
            name="Watched Users",
            value=f"`{len(users)}`",
            inline=True
        )

        if log_channel:

            embed.add_field(
                name="Log Channel",
                value=log_channel.mention,
                inline=True
            )

            log_status = "🟢 Online"

        else:

            embed.add_field(
                name="Log Channel",
                value="❌ Not configured",
                inline=True
            )

            log_status = "🔴 Not configured"

        embed.add_field(
            name="Logging",
            value=log_status,
            inline=True
        )

        if users:

            lines = []

            for user_id, data in users.items():

                try:
                    numeric_id = int(user_id)

                except (TypeError, ValueError):
                    numeric_id = 0

                member = (
                    ctx.guild.get_member(numeric_id)
                    if numeric_id
                    else None
                )

                if member:

                    display_name = member.display_name
                    username = member.name

                    lines.append(
                        f"• {member.mention}\n"
                        f"  **Name:** {display_name}\n"
                        f"  **Username:** `@{username}`\n"
                        f"  **ID:** `{user_id}`"
                    )

                else:

                    display_name = data.get(
                        "display_name",
                        "Unknown User"
                    )

                    username = data.get(
                        "username",
                        "Unknown"
                    )

                    lines.append(
                        f"• <@{user_id}>\n"
                        f"  **Name:** {display_name}\n"
                        f"  **Username:** `@{username}`\n"
                        f"  **ID:** `{user_id}`\n"
                        f"  ⚠️ Not currently cached in server"
                    )

            # Discord allows a maximum of 1024 chars per field.
            chunks = []
            current = []

            for line in lines:

                candidate = "\n\n".join(
                    current + [line]
                )

                if len(candidate) > 1000:

                    if current:
                        chunks.append(
                            "\n\n".join(current)
                        )

                    current = [line]

                else:

                    current.append(line)

            if current:
                chunks.append(
                    "\n\n".join(current)
                )

            for index, chunk in enumerate(chunks[:25]):

                embed.add_field(
                    name=(
                        "Watched Users"
                        if index == 0
                        else f"Watched Users {index + 1}"
                    ),
                    value=chunk,
                    inline=False
                )

        else:

            embed.add_field(
                name="Watched Users",
                value="No users are currently being watched.",
                inline=False
            )

        embed.set_footer(
            text="Watch List • Separate from the main Logger"
        )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    @discord.slash_command(name="watch_info", description="Show information about a watched user.")
    async def watch_info(self, ctx: discord.ApplicationContext, user: discord.Option(discord.Member, "User to inspect") ): # type: ignore
        """
        Show information about one watched user.
        """

        if not await self._check_admin(ctx):
            return

        data = self._get_watched_user(
            ctx.guild.id,
            user.id
        )

        if data is None:

            await ctx.respond(
                f"❌ {user.mention} is not currently on the watch list.",
                ephemeral=True
            )

            return

        embed = discord.Embed(
            title="👁️ Watch List User Information",
            color=discord.Color.orange()
        )

        avatar_url = self._member_avatar_url(user)

        if avatar_url:
            embed.set_thumbnail(
                url=avatar_url
            )

        embed.add_field(
            name="User",
            value=(
                f"{user.mention}\n"
                f"**Username:** `@{user.name}`\n"
                f"**Display Name:** `{user.display_name}`"
            ),
            inline=False
        )

        embed.add_field(
            name="Discord ID",
            value=f"`{user.id}`",
            inline=True
        )

        added_by_id = data.get(
            "added_by"
        )

        if added_by_id:

            added_by = ctx.guild.get_member(
                int(added_by_id)
            )

            if added_by:

                added_by_value = (
                    f"{added_by.mention}\n"
                    f"`{added_by.id}`"
                )

            else:

                added_by_value = (
                    f"<@{added_by_id}>\n"
                    f"`{added_by_id}`"
                )

        else:

            added_by_value = "Unknown"

        embed.add_field(
            name="Added By",
            value=added_by_value,
            inline=True
        )

        added_at = data.get(
            "added_at"
        )

        if added_at:

            try:
                parsed = datetime.fromisoformat(
                    added_at.replace(
                        "Z",
                        "+00:00"
                    )
                )

                added_timestamp = int(
                    parsed.timestamp()
                )

                added_value = (
                    f"<t:{added_timestamp}:F>\n"
                    f"<t:{added_timestamp}:R>"
                )

            except Exception:

                added_value = f"`{added_at}`"

        else:

            added_value = "Unknown"

        embed.add_field(
            name="Added",
            value=added_value,
            inline=False
        )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    @discord.slash_command(name="watch_set_channel",description="Set the channel where watch-list messages are logged.")
    async def watch_set_channel(self, ctx: discord.ApplicationContext, channel: discord.Option(discord.TextChannel, "Channel for watch-list logs") ): # type: ignore
        """
        Set the watch-list logging channel.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(
            ctx.guild.id
        )

        guild_data["log_channel_id"] = str(
            channel.id
        )

        self._save_db()

        embed = discord.Embed(
            title="👁️ Watch List Log Channel Updated",
            color=discord.Color.green()
        )

        embed.add_field(
            name="Log Channel",
            value=channel.mention,
            inline=False
        )

        embed.add_field(
            name="Channel ID",
            value=f"`{channel.id}`",
            inline=True
        )

        embed.add_field(
            name="Status",
            value="🟢 Enabled",
            inline=True
        )

        await ctx.respond(
            embed=embed,
            ephemeral=True
        )

    @discord.slash_command(name="watch_clear", description="Remove every user from the watch list.")
    async def watch_clear(self, ctx: discord.ApplicationContext):
        """
        Clear the entire watch list.

        Requires typing CONFIRM so this can't be accidentally
        triggered.
        """

        if not await self._check_admin(ctx):
            return

        guild_data = self._guild_data(
            ctx.guild.id
        )

        users = guild_data.get(
            "users",
            {}
        )

        if not users:

            await ctx.respond(
                "👁️ The watch list is already empty.",
                ephemeral=True
            )

            return

        # ----------------------------------------------------
        # Confirmation view
        # ----------------------------------------------------

        class ConfirmView(discord.ui.View):

            def __init__(self, cog, author_id):
                super().__init__(timeout=30)

                self.cog = cog
                self.author_id = author_id
                self.confirmed = False

            async def interaction_check(
                self,
                interaction: discord.Interaction
            ):
                if interaction.user.id != self.author_id:

                    await interaction.response.send_message(
                        "❌ You cannot use this confirmation.",
                        ephemeral=True
                    )

                    return False

                return True

            @discord.ui.button(
                label="Clear Watch List",
                style=discord.ButtonStyle.danger,
                emoji="🗑️"
            )
            async def confirm(
                self,
                button,
                interaction
            ):
                guild_data = self.cog._guild_data(
                    interaction.guild.id
                )

                count = len(
                    guild_data.get(
                        "users",
                        {}
                    )
                )

                guild_data["users"] = {}

                self.cog._save_db()

                self.confirmed = True

                for child in self.children:
                    child.disabled = True

                await interaction.response.edit_message(
                    content=(
                        f"🗑️ Cleared **{count}** "
                        f"user(s) from the watch list."
                    ),
                    embed=None,
                    view=self
                )

                self.stop()

            @discord.ui.button(
                label="Cancel",
                style=discord.ButtonStyle.secondary,
                emoji="❌"
            )
            async def cancel(
                self,
                button,
                interaction
            ):
                for child in self.children:
                    child.disabled = True

                await interaction.response.edit_message(
                    content="❌ Watch-list clear cancelled.",
                    embed=None,
                    view=self
                )

                self.stop()

            async def on_timeout(self):
                for child in self.children:
                    child.disabled = True

        embed = discord.Embed(
            title="⚠️ Clear Watch List",
            description=(
                f"This will remove **{len(users)}** "
                f"user(s) from the watch list.\n\n"
                "This does **not** delete message logs that have "
                "already been sent to Discord.\n\n"
                "Are you sure?"
            ),
            color=discord.Color.red()
        )

        await ctx.respond(
            embed=embed,
            view=ConfirmView(
                self,
                ctx.author.id
            ),
            ephemeral=True
        )



    @commands.Cog.listener()
    async def on_application_command_error(self,ctx,error):
        """
        Prevent watch-list command errors from becoming
        confusing unhandled task errors.
        """

        # Only handle errors belonging to this cog's commands.
        try:
            command = getattr(
                ctx,
                "command",
                None
            )

            if command is None:
                return

            command_name = getattr(
                command,
                "name",
                ""
            )

            if not str(command_name).startswith(
                "watch_"
            ):
                return

        except Exception:
            return

        print(
            f"[WatchList] Command error: {error}"
        )

        try:

            if ctx.response.is_done():

                await ctx.followup.send(
                    "❌ Something went wrong while running that watch-list command.",
                    ephemeral=True
                )

            else:

                await ctx.respond(
                    "❌ Something went wrong while running that watch-list command.",
                    ephemeral=True
                )

        except Exception:
            pass



def setup(bot):
    bot.add_cog(
        WatchList(bot)
    )