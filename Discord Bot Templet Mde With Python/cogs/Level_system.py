# cogs/level_system.py
import time
import discord
from discord.ext import commands
import random

from config import admin_required, extra_help, GUILD_IDS
from data.DB.Storage.storage import get_levels, save_levels, get_xp, save_xp

COOLDOWN_LEVEL = 30
COOLDOWN_LEADERBOARD = 30
GAME_XP_DEFAULT = True  # Eat It or Yeet It votes earn level XP unless toggled off


async def game_xp_enabled(guild_id):
    """Whether game votes earn level XP (per-server toggle, default on)."""
    db = await get_levels(str(guild_id))
    return db.get("settings", {}).get("game_xp", GAME_XP_DEFAULT)


async def apply_level_rewards(guild, user_id, level, settings):
    """Grant level-role rewards the member has earned (cumulative)."""
    rewards = settings.get("level_roles", {})
    if not rewards:
        return
    member = guild.get_member(int(user_id))
    if member is None:
        return
    for lvl_str, role_id in rewards.items():
        try:
            if level < int(lvl_str):
                continue
            role = guild.get_role(int(role_id))
            if role is not None and role not in member.roles:
                await member.add_roles(role, reason=f"Level reward: reached level {lvl_str}")
        except (ValueError, discord.HTTPException):
            continue


async def announce_level_up(guild, user_id, level, settings, fallback_channel=None):
    """Post a level-up message to the configured channel, or the fallback."""
    channel = None
    channel_id = settings.get("levelup_channel_id")
    if channel_id:
        try:
            channel = guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
    if channel is None:
        channel = fallback_channel
    if channel is None:
        return
    try:
        await channel.send(f"🎉 <@{user_id}> leveled up to **{level}**!")
    except discord.HTTPException:
        pass


async def award_xp(guild, user_id, display_name, amount, fallback_channel=None):
    """Award XP, handling level-ups, role rewards, and announcements.

    Returns the list of new levels reached (empty if none).
    """
    gid, uid = str(guild.id), str(user_id)
    db = await get_levels(gid)
    settings = db.setdefault("settings", {})
    user_data = db.setdefault(uid, {"xp": 0, "level": 1, "username": display_name})
    user_data["username"] = display_name
    user_data["xp"] += amount
    gained = []
    while user_data["xp"] >= user_data["level"] * 100:
        user_data["xp"] -= user_data["level"] * 100
        user_data["level"] += 1
        gained.append(user_data["level"])
    await save_levels(gid, db)
    if gained:
        await apply_level_rewards(guild, user_id, user_data["level"], settings)
        await announce_level_up(guild, user_id, user_data["level"], settings, fallback_channel)
    return gained

class LevelSystem(commands.Cog):
    HelpCategory = "Level System"

    def __init__(self, bot):
        self.bot = bot
        self.cooldowns_level = {}
        self.cooldowns_lb = {}

    def calculate_level_progress(self, xp, level):
        xp_needed = level * 100
        return min((xp / xp_needed) * 100 if xp_needed else 0, 100)

    def create_progress_bar(self, progress, length=20):
        filled = int((progress / 100) * length)
        return "█" * filled + "░" * (length - filled)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid = str(message.guild.id)
        uid = str(message.author.id)

        db = await get_levels(gid)
        settings = db.get("settings", {})
        cooldown = settings.get("cooldown", 0)

        now = time.time()
        if cooldown:
            timestamps = await get_xp(gid)
            if now - timestamps.get(uid, 0) < cooldown:
                return
            timestamps[uid] = now
            await save_xp(gid, timestamps)

        lo, hi = settings.get("xp_min", 1), settings.get("xp_max", 5)
        if lo > hi:  # guard against bad data saved before validation existed
            lo, hi = hi, lo
        xp_gain = random.randint(lo, hi)

        await award_xp(message.guild, message.author.id, message.author.display_name,
                       xp_gain, fallback_channel=message.channel)

    @commands.slash_command(name="set_xp_rate", description="Set XP gain range per message")
    @extra_help("Set the minimum and maximum XP that can be gained per message.")
    @admin_required()
    async def set_xp_rate(self, interaction, minimum: int, maximum: int):
        if minimum < 0 or maximum < 0:
            return await interaction.respond("XP values can't be negative.", ephemeral=True)
        if minimum > maximum:
            return await interaction.respond("Minimum can't be higher than maximum.", ephemeral=True)
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["xp_min"] = minimum
        db["settings"]["xp_max"] = maximum
        await save_levels(gid, db)
        await interaction.respond(f"✅ XP gain range set to {minimum}–{maximum} XP/msg")

    @commands.slash_command(name="set_cooldown", description="Set XP gain cooldown (sec)")
    @extra_help("Set the cooldown in seconds between XP gains per user. Set to 0 for no cooldown.")
    @admin_required()
    async def set_cooldown(self, interaction, seconds: int):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["cooldown"] = seconds
        await save_levels(gid, db)
        await interaction.respond(f"✅ Cooldown set to {seconds}s")

    @commands.slash_command(name="set_level_channel", description="Set level-up message channel")
    @extra_help("Set the channel where level-up messages will be posted.")
    @admin_required()
    async def set_level_channel(self, interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["levelup_channel_id"] = str(channel.id)
        await save_levels(gid, db)
        await interaction.respond(f"✅ Level-up messages will post in {channel.mention}")

    @commands.slash_command(name="level", description="Check your or another user's level")
    @extra_help("Check your level or another user's level and XP progress.")
    async def level(self, interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        gid, uid = str(interaction.guild.id), str(target.id)

        now = time.time()
        last = self.cooldowns_level.setdefault(gid, {}).get(uid, 0)
        if now - last < COOLDOWN_LEVEL:
            return await interaction.followup.send(f"⏳ Try again in {round(COOLDOWN_LEVEL - (now - last), 1)}s!")
        self.cooldowns_level[gid][uid] = now

        db = await get_levels(gid)
        user = db.get(uid)
        if not user:
            return await interaction.followup.send("No level data found for that user.")

        xp = user.get("xp", 0)
        level = user.get("level", 1)
        progress = self.calculate_level_progress(xp, level)
        progress_bar = self.create_progress_bar(progress)

        embed = discord.Embed(title="📊 Level Status", color=discord.Color.blue())
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.add_field(name="Level", value=level, inline=True)
        embed.add_field(name="XP Progress", value=f"{progress_bar} ({xp}/{level * 100} XP)", inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)

        await interaction.followup.send(embed=embed)

    @commands.slash_command(name="leaderboard", description="Show XP leaderboard")
    @extra_help("View the top 10 users by level and XP in this server.")
    async def leaderboard(self, interaction):
        await interaction.response.defer()
        gid, uid = str(interaction.guild.id), str(interaction.user.id)

        now = time.time()
        last = self.cooldowns_lb.setdefault(gid, {}).get(uid, 0)
        if now - last < COOLDOWN_LEADERBOARD:
            return await interaction.followup.send(f"⏳ Try again in {round(COOLDOWN_LEADERBOARD - (now - last), 1)}s!")
        self.cooldowns_lb[gid][uid] = now

        db = await get_levels(gid)
        user_data = {k: v for k, v in db.items() if k != "settings"}
        top = sorted(user_data.items(), key=lambda i: (i[1]["level"], i[1]["xp"]), reverse=True)[:10]

        embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold())
        for i, (uid, d) in enumerate(top, 1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else d.get("username", f"User ID {uid}")
            embed.add_field(name=f"#{i} {name}", value=f"Lv {d['level']} — {d['xp']} XP", inline=False)

        await interaction.followup.send(embed=embed)

    @commands.slash_command(name="add_xp", description="Add XP to a user")
    @extra_help("Add XP to a user. Admins only. Level-ups are announced like normal.")
    @admin_required()
    async def add_xp(self, interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.respond(
                "Amount must be positive \u2014 use /resetxp to wipe someone's progress.",
                ephemeral=True)
        gained = await award_xp(interaction.guild, member.id, member.display_name,
                                amount, fallback_channel=interaction.channel)
        db = await get_levels(str(interaction.guild.id))
        user_data = db[str(member.id)]
        xp_needed = user_data["level"] * 100
        if gained:
            await interaction.respond(
                f"\u2705 Added {amount} XP to {member.mention} \u2014 they leveled up to "
                f"**{user_data['level']}**! \U0001f389")
        else:
            xp_remaining = xp_needed - user_data["xp"]
            await interaction.respond(
                f"\u2705 Added {amount} XP to {member.mention}\n"
                f"\U0001f4c8 Level: {user_data['level']} \u2014 XP: {user_data['xp']}/{xp_needed} "
                f"(\U0001f9ee {xp_remaining} XP to next level)"
            )

    @commands.slash_command(name="resetxp", description="Reset XP and level for a user")
    @extra_help("Reset a user's XP and level to 0 and 1 respectively. Admins only.")
    @admin_required()
    async def resetxp(self, interaction, member: discord.Member):
        gid, uid = str(interaction.guild.id), str(member.id)
        db = await get_levels(gid)

        if uid in db:
            db[uid] = {"xp": 0, "level": 1, "username": member.display_name}
            await save_levels(gid, db)
            await interaction.respond(f"✅ Reset data for {member.display_name}.")
        else:
            await interaction.respond("User not found.")

    @commands.slash_command(name="cleardata", description="Clear all level data for this server")
    @extra_help("Clear all level data for this server. Admins only.")
    @admin_required()
    async def cleardata(self, interaction):
        await save_levels(str(interaction.guild.id), {})
        await interaction.respond("⚠️ All data cleared for this server.")

    @commands.slash_command(name="getxpsettings", description="View current XP settings")
    @extra_help("View current XP gain, cooldown, level-up channel, role rewards, and game XP toggle.")
    async def getxpsettings(self, interaction):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.get("settings", {})

        embed = discord.Embed(title="📊 XP Settings", color=discord.Color.blue())
        embed.add_field(name="⏳ Cooldown", value=f"{settings.get('cooldown', 0)}s", inline=False)
        embed.add_field(name="📈 XP Gain", value=f"{settings.get('xp_min', 1)} - {settings.get('xp_max', 5)}", inline=False)
        channel_id = settings.get("levelup_channel_id")
        embed.add_field(name="📢 Level-up Channel",
                        value=f"<#{channel_id}>" if channel_id else "Not set (uses current channel)",
                        inline=False)
        rewards = settings.get("level_roles", {})
        if rewards:
            lines = []
            for lvl in sorted(rewards, key=int):
                lines.append(f"Level {lvl}: <@&{rewards[lvl]}>")
            embed.add_field(name="🎖️ Role Rewards", value="\n".join(lines), inline=False)
        else:
            embed.add_field(name="🎖️ Role Rewards", value="None set", inline=False)
        game_xp = settings.get("game_xp", GAME_XP_DEFAULT)
        embed.add_field(name="🎮 Game XP", value="ON" if game_xp else "OFF", inline=False)

        await interaction.respond(embed=embed)

    @commands.slash_command(name="set_level_role", description="Set a role reward for reaching a level")
    @extra_help("Members automatically receive the role when they reach the level. Rewards are cumulative.")
    @admin_required()
    async def set_level_role(self, interaction, level: int, role: discord.Role):
        if level < 2:
            return await interaction.respond("Level must be at least 2.", ephemeral=True)
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        rewards = db.setdefault("settings", {}).setdefault("level_roles", {})
        rewards[str(level)] = str(role.id)
        await save_levels(gid, db)
        await interaction.respond(f"✅ {role.mention} will be awarded at level **{level}**.")

    @commands.slash_command(name="remove_level_role", description="Remove a level role reward")
    @extra_help("Stops awarding a role at the given level (members who already have it keep it).")
    @admin_required()
    async def remove_level_role(self, interaction, level: int):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        rewards = db.setdefault("settings", {}).setdefault("level_roles", {})
        if str(level) in rewards:
            del rewards[str(level)]
            await save_levels(gid, db)
            await interaction.respond(f"✅ Removed the role reward for level **{level}**.")
        else:
            await interaction.respond(f"No role reward is set for level {level}.", ephemeral=True)

    @commands.slash_command(name="toggle_game_xp", description="Toggle XP for Eat It or Yeet It votes", guild_ids=GUILD_IDS)
    @extra_help("Turns on/off level XP earned by voting in Eat It or Yeet It. On by default.")
    @admin_required()
    async def toggle_game_xp(self, interaction):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        new_val = not settings.get("game_xp", GAME_XP_DEFAULT)
        settings["game_xp"] = new_val
        await save_levels(gid, db)
        state = "ON" if new_val else "OFF"
        detail = "voting now earns level XP" if new_val else "voting no longer earns level XP"
        await interaction.respond(f"🎮 Game XP is now **{state}** — {detail}.")

def setup(client):
    client.add_cog(LevelSystem(client))
