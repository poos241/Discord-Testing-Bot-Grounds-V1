# cogs/admin_cog.py
import time
import discord
from discord.ext import commands
import os
import sys
import subprocess
import asyncio
from config import  GUILD_IDS, admin_required, is_owner, load_json, save_json, autocomplete_commands , extra_help


class AdminCog(commands.Cog):
    """Admin commands (e.g. clear_user)."""
    def __init__(self, client):
        self.bot = client
        self.cooldownRenamebot = {}  # Initialize cooldowns here
        self.COOLDOWN_SECONDS_Remame_bot = 500

        
        
     
        
    @discord.slash_command(name="clear_user", description="Clear messages from a user across one or all channels.")
    @extra_help("Clears messages from a specific user in one or all channels. You can specify a user by selecting them or by providing their ID. You can also choose a specific channel to clear messages from.")
    @admin_required()
    async def clear_user(
            self,
            interaction: discord.ApplicationContext,
            target_user: discord.Option(discord.User, "pick the user you wish to clear messages from ", default= None, required=False), # type: ignore
            user_id: discord.Option(str, "put in a users discord id if there no longer in the server", default= None, required=False), # type: ignore
            channel: discord.Option(discord.TextChannel, "pick a channel to clear messages from",  default= None, required=False),  # type: ignore
            amount: discord.Option (int, "set the amount of messages to clear from a user default 100",  default= 100, required=False) # type: ignore
        ):
            """Clear messages from a user in one or all channels."""
            resolved_user_id = None
            user_display = None

            if target_user:
                resolved_user_id = target_user.id
                user_display = f"{target_user.display_name} ({target_user.name}#{target_user.discriminator})"
            elif user_id and user_id.isdigit():
                resolved_user_id = int(user_id)
                try:
                    user_obj = await self.bot.fetch_user(resolved_user_id)
                    user_display = f"ID `{resolved_user_id}`"
                except discord.NotFound:
                    await interaction.followup.send("❌ User with the provided ID not found.", ephemeral=True)
                    return
            else:
                await interaction.followup.send("❌ You must specify a user (via selection or ID).", ephemeral=True)
                return

            def is_target_user(msg):
                return msg.author.id == resolved_user_id

            channels_to_scan = (
                [channel] if channel
                else [
                    ch for ch in interaction.guild.text_channels
                    if ch.permissions_for(interaction.guild.me).read_message_history and
                    ch.permissions_for(interaction.guild.me).manage_messages
                ]
            )

            total_deleted = 0
            per_channel_summary = []

            await interaction.response.defer(ephemeral=True)

            for ch in channels_to_scan:
                deleted = await ch.purge(limit=amount, check=is_target_user)
                total_deleted += len(deleted)
                per_channel_summary.append(f"Deleted {len(deleted)} messages in {ch.mention}")

            summary_message = f"✅ Finished clearing messages for {user_display}.\n" + "\n".join(per_channel_summary)
            await interaction.followup.send(summary_message, ephemeral=True)



   
    # User Info Command
    @discord.slash_command(name = "userinfo")
    @extra_help("View information about a user in the server. You can specify a user by selecting them or by providing their ID. If no user is specified, it will show your own information.")
    @admin_required()
    async def userinfo(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "pick a user to see info about them in the discord", default=None) # type: ignore
        ):
        """View information about a user in the server."""
        cooldownUserInfo = {}
        COOLDOWN_SECONDS_User_Info = 60
        await interaction.response.defer()
        user_id = interaction.author.id
        guild_id = interaction.guild.id
        now = time.time()
        join_timestamp = int(member.joined_at.timestamp())
        formatted_date = f"<t:{join_timestamp}:F>"
        # Ensure guild key exists
        if guild_id not in cooldownUserInfo:
            cooldownUserInfo[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = cooldownUserInfo[guild_id]

        # Check cooldown
        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < COOLDOWN_SECONDS_User_Info:
                remaining = round(COOLDOWN_SECONDS_User_Info - elapsed, 1)
                await interaction.followup.send(f"⏳ You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[user_id] = now




        if member is None:
            member = interaction.author
        elif member is not None:
            member = member
            info_embed= discord.Embed(title=f"{member.name} ({member.display_name})`s User Information", description="All information about this user.", color=member.color)
            roles = ", ".join(r.name for r in member.roles if r.name != "@everyone") or "None"
            info_embed.set_thumbnail(url=member.avatar)
            info_embed.add_field(name="Name:", value=member.name, inline=False)
            info_embed.add_field(name="Nick Name:", value=member.display_name, inline= False)
            info_embed.add_field(name="Discriminator:", value=member.discriminator, inline=False)
            info_embed.add_field(name="ID:", value=member.id, inline=False)
            info_embed.add_field(name="Top Role:", value=member.top_role, inline=False)
            info_embed.add_field(name="All Roles:", value=roles, inline=False)
            info_embed.add_field(name="status:", value=member.status, inline=False)
            info_embed.add_field(name="bot User?", value=member.bot, inline=False)
            info_embed.add_field(name="creation Date:", value=f"<t:{int(member.created_at.timestamp())}:F>", inline=False)
            info_embed.add_field(name="join Date:", value=formatted_date, inline=False)
        await interaction.send(embed=info_embed)


    @discord.slash_command(name='remove_user_role', description="use this to remove a users role")
    @extra_help("Remove a role from a user in the server. You can specify a user by selecting them or by providing their ID. You can also choose a specific role to remove.")
    @admin_required() 
    async def remove_user_role(
        self,
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to remove a role from"), # type: ignore 
        role: discord.Option(discord.Role, "pick the role to remove from the user"), # type: ignore
        ):
        """Remove a role from a user in the server."""
        if role is None: # This check might not be needed because if a role cannot be resolved, the command might not be triggered.
            await interaction.respond(f"Role not found.", ephemeral=True)
            return

        if role not in member.roles:
            await interaction.respond(f"{member.display_name} doesn't have the role '{role.name}'.", ephemeral=True) # Use role.name
            return

        try:
            await member.remove_roles(role)
            await interaction.respond(f"Removed role '{role.name}' from {member.display_name}.", ephemeral=True)
        except discord.Forbidden:
            await interaction.respond(f"I don't have permission to remove the role '{role.name}'. Please ensure my role is above this role in the hierarchy.", ephemeral=True)
        except Exception as e:
            await interaction.respond(f"An error occurred: {e}")


    @discord.slash_command(name="add_user_role", description="use this to give a role to a user in the server")
    @extra_help("Add a role to a user in the server. You can specify a user by selecting them or by providing their ID. You can also choose a specific role to add.")
    @admin_required()  
    async def add_user_role(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "use this to pick a user to add a role from"), # type: ignore  
        role: discord.Option(discord.Role,"this is is used to pick the role to set for the user"), # type: ignore
        ):
        """Add a role to a user in the server.""" 
        if role is None:
            await interaction.response.send_message(f"Role not found.", ephemeral=True) # Changed from respond to response.send_message
            return

        if role in member.roles:
            await interaction.response.send_message(f"{member.display_name} already has the role '{role.name}'.", ephemeral=True) # Changed from respond to response.send_message
            return
        
        try:
            await member.add_roles(role)
            await interaction.response.send_message(f"Successfully added the role '{role.name}' to {member.display_name}.", ephemeral=True) # Success message
        except discord.Forbidden:   
            await interaction.response.send_message(f"I don't have permission to add the role '{role.name}'. Please ensure my role is above this role in the hierarchy.", ephemeral=True) # Changed from respond to response.send_message
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}", ephemeral=True) # Changed from respond to response.send_message and added ephemeral=True

        
        
        
        
        
        
      
    
    @discord.slash_command(name="rename_bot", description="used by the admins to change the name of the bot in there discord server")
    @extra_help("Rename the bot in your server. You can set a new nickname for the bot, but ensure it doesn't violate Discord's naming policies.")
    @admin_required()
    async def rename_bot(
        self,
        interaction: discord.ApplicationContext,
        new_nick: str = discord.Option(str, description="set the name of the bot") # Corrected Option usage
        ):
        """Rename the bot in the server."""
        await interaction.response.defer()
        user_id = interaction.author.id
        guild_id = interaction.guild.id
        now = time.time()

        # Ensure guild key exists
        if guild_id not in self.cooldownRenamebot:
            self.cooldownRenamebot[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = self.cooldownRenamebot[guild_id]

        # Check cooldown
        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < self.COOLDOWN_SECONDS_Remame_bot:
                remaining = round(self.COOLDOWN_SECONDS_Remame_bot - elapsed, 1)
                await interaction.followup.send(f"⏳ You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[user_id] = now
        try:
            # Need to get the bot's member object in the guild
            bot_member = interaction.guild.me
            await bot_member.edit(nick=new_nick) # Use the bot's member object to change the nickname
            await interaction.followup.send(f"Bot renamed to **{new_nick}** in **{interaction.guild.name}**") # Use followup.send after deferring
        except discord.Forbidden: # Handle specific permission error
            await interaction.followup.send("I couldn't rename myself. Please check my permissions (Manage Nicknames)!") # Provide helpful error message
        except Exception as e:
            await interaction.followup.send(f"An error occurred: {e}") # Use followup.send for general errors as well
          

    @discord.slash_command(name="rename_user", description="used by the admins to change the name a user in there discord server")
    @extra_help("Rename a user in your server. You can set a new nickname for the user, but ensure it doesn't violate Discord's naming policies.")
    @admin_required()
    async def rename_user(
        self, interaction: discord.ApplicationContext, 
        member: discord.Option(discord.Member, "pick the name of the user you want to change"), # type: ignore 
        new_nick: discord.Option(str, "set the name of the user ") # type: ignore
        ):
        """Rename a user in the server."""
        cooldownRenameuser = {}
        COOLDOWN_SECONDS_Rename_User = 5 
        await interaction.response.defer()
        user_id = interaction.author.id
        guild_id = interaction.guild.id
        now = time.time()

        # Ensure guild key exists
        if guild_id not in cooldownRenameuser:
            cooldownRenameuser[guild_id] = {}

        # Reference the user_cooldowns for this guild
        user_cooldowns = cooldownRenameuser[guild_id]

        # Check cooldown
        if user_id in user_cooldowns:
            elapsed = now - user_cooldowns[user_id]
            if elapsed < COOLDOWN_SECONDS_Rename_User:
                remaining = round(COOLDOWN_SECONDS_Rename_User - elapsed, 1)
                await interaction.followup.send(f"⏳ You're on cooldown {interaction.author.mention}! Try again in {remaining} seconds.")
                return

        # Set new cooldown
        user_cooldowns[user_id] = now
        try:
            await member.edit(nick=new_nick)
            await interaction.send(f"user name changed to **{member.mention}** in **{interaction.guild.name}**")
        except Exception as e:
            await interaction.send("can't find the user in the discord")



    @discord.slash_command(name="reset_user_name", description="used by the admins to reset the useers name")
    @extra_help("Reset a user's nickname in your server. This will remove any custom nickname they have set.")
    @admin_required()
    async def reset_user_name(
        self, 
        interaction: discord.ApplicationContext,
        member: discord.Option(discord.Member, "Pick the user to reset there name ") # type: ignore
        ):
        """Reset a user's nickname in the server."""
        try:
            await member.edit(nick=None)
            await interaction.respond(f"{member.mention}'s nickname was reset in **{interaction.guild.name}**.")
        except Exception:
            await interaction.respond("I couldn't reset that user's nickname. Do I have permission?")
     
        
    @discord.slash_command(name="shutdown_bot",description="Make the bot shutdown.",)
    @extra_help("Shuts down the bot. Use this command with caution as it will stop the bot from running until restarted.")
    @is_owner()
    async def shutdown(self, interaction: discord.ApplicationContext) -> None:
        """Shuts down the bot."""
        embed = discord.Embed(description="Shutting down. Bye! :wave:", color=0xBEBEFE)
        await interaction.send(embed=embed)
        await self.bot.close()

    
    
    @discord.slash_command(name="restart_bot", description="Restarts the bot.")
    @extra_help("Restarts the bot. Use this command with caution as it will stop the bot and start it again.")
    @is_owner()
    async def restart(self, ctx: discord.ApplicationContext):
        """Restarts the bot."""
        embed = discord.Embed(description="Restarting... Be right back! 🔁", color=0xBEBEFE)
        await ctx.respond(embed=embed)

        # Windows-friendly restart using subprocess
        python = sys.executable
        subprocess.Popen([python] + sys.argv)

        await self.bot.close()
    

        

def setup(client):
    client.add_cog(AdminCog(client))
