# cogs/level_system.py
import io
import os
import zipfile
import time
import discord
from asyncio import Lock
from discord.ext import commands
import random

from config import admin_required, extra_help
from data.DB.Storage.storage import get_levels, save_levels, get_xp, save_xp

COOLDOWN_LEVEL = 120
COOLDOWN_LEADERBOARD = 120

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
        timestamps = await get_xp(gid)

        guild_settings = db.setdefault("settings", {})
        guild_settings["guild_name"] = message.guild.name  # ✅ ADD THIS
        cooldown = guild_settings.get("cooldown", 0)

        now = time.time()
        last_ts = timestamps.get(uid, 0)
        if cooldown and now - last_ts < cooldown:
            return

        xp_gain = random.randint(
            guild_settings.get("xp_min", 1),
            guild_settings.get("xp_max", 5)
        )

        user_data = db.setdefault(uid, {
            "xp": 0,
            "level": 1,
            "username": message.author.display_name,
            "guild_name": message.guild.name
        })

        user_data["guild_name"] = message.guild.name
        user_data["username"] = message.author.display_name
        user_data["xp"] += xp_gain
        timestamps[uid] = now

        while user_data["xp"] >= user_data["level"] * 100:
            user_data["xp"] -= user_data["level"] * 100
            user_data["level"] += 1

            lvl_channel_id = guild_settings.get("levelup_channel_id")
            if lvl_channel_id:
                chan = message.guild.get_channel(int(lvl_channel_id))
                if chan:
                    await chan.send(
                        f"🎉 {message.author.mention} leveled up to **{user_data['level']}**!"
                    )
        db.setdefault("settings", {})["guild_name"] = message.guild.name
        await save_levels(gid, db)
        await save_xp(gid, timestamps)

    @commands.slash_command(name="set_xp_rate", description="Set XP gain range per message")
    @extra_help("Set the minimum and maximum XP that can be gained per message.")
    @admin_required()
    async def set_xp_rate(self, interaction, minimum: int, maximum: int):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["xp_min"] = minimum
        db["settings"]["xp_max"] = maximum
        db.setdefault("settings", {})["guild_name"] = interaction.guild.name
        await save_levels(gid, db)
        await interaction.respond(f"✅ XP gain range set to {minimum}–{maximum} XP/msg")

    @commands.slash_command(name="set_cooldown", description="Set XP gain cooldown (sec)")
    @extra_help("Set the cooldown in seconds between XP gains per user. Set to 0 for no cooldown.")
    @admin_required()
    async def set_cooldown(self, interaction, seconds: int):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["cooldown"] = seconds
        db.setdefault("settings", {})["guild_name"] = interaction.guild.name
        await save_levels(gid, db)
        await interaction.respond(f"✅ Cooldown set to {seconds}s")

    @commands.slash_command(name="set_level_channel", description="Set level-up message channel")
    @extra_help("Set the channel where level-up messages will be posted.")
    @admin_required()
    async def set_level_channel(self, interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["levelup_channel_id"] = str(channel.id)
        db.setdefault("settings", {})["guild_name"] = interaction.guild.name
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
            return await interaction.respond("No level data found for that user.")

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
            name = member.display_name if member else f"User ID {uid}"
            embed.add_field(name=f"#{i} {name}", value=f"Lv {d['level']} — {d['xp']} XP", inline=False)

        await interaction.followup.send(embed=embed)

    @commands.slash_command(name="add_xp", description="Add XP to a user")
    @extra_help("Add XP to a user. Admins only.")
    @admin_required()
    async def add_xp(self, interaction, member: discord.Member, amount: int):
        gid, uid = str(interaction.guild.id), str(member.id)

        db = await get_levels(gid)
        db.setdefault("settings", {})["guild_name"] = interaction.guild.name
        user_data = db.setdefault(uid, {
            "xp": 0,
            "level": 1,
            "username": member.display_name,
            "guild_name": interaction.guild.name,
            "last_levelup": None
        })

        user_data["username"] = member.display_name
        user_data["xp"] += amount

        now = time.time()
        while user_data["xp"] >= user_data["level"] * 100:
            user_data["xp"] -= user_data["level"] * 100
            user_data["level"] += 1
            user_data["last_levelup"] = now

        xp_needed = user_data["level"] * 100
        xp_remaining = xp_needed - user_data["xp"]
        db.setdefault("settings", {})["guild_name"] = interaction.guild.name
        await save_levels(gid, db)
        await interaction.respond(
            f"✅ Added {amount} XP to {member.mention}\n"
            f"📈 Level: {user_data['level']} — XP: {user_data['xp']}/{xp_needed} "
            f"(🧮 {xp_remaining} XP to next level)"
        )

    @commands.slash_command(name="resetxp", description="Reset XP and level for a user")
    @extra_help("Reset a user's XP and level to 0 and 1 respectively. Admins only.")
    @admin_required()
    async def resetxp(self, interaction, member: discord.Member):
        gid, uid = str(interaction.guild.id), str(member.id)
        db = await get_levels(gid)

        if uid in db:
            db[uid] = {
                "xp": 0, "level": 1,
                "username": member.display_name,
                "guild_name": interaction.guild.name
            }
            db.setdefault("settings", {})["guild_name"] = interaction.guild.name
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
    @extra_help("View current XP gain, cooldown, and level-up channel settings.")
    async def getxpsettings(self, interaction):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.get("settings", {})

        if not settings:
            embed = discord.Embed(title="📊 XP Settings Not Found",
                                  description="No XP settings have been configured for this server.",
                                  color=discord.Color.red())
        else:
            embed = discord.Embed(title="📊 XP Settings", color=discord.Color.red())
            embed.add_field(name="⏳ Cooldown", value=f"{settings.get('cooldown', 0)}s", inline=False)
            embed.add_field(name="📈 XP Gain", value=f"{settings.get('xp_min', 1)} - {settings.get('xp_max', 5)}", inline=False)
            embed.add_field(name="📢 Level-up Channel", value=f"<#{settings.get('levelup_channel_id', 'unset')}>", inline=False)

        await interaction.respond(embed=embed)

def setup(client):
    client.add_cog(LevelSystem(client))
