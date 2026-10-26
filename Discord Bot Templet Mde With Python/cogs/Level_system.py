# cogs/level_system.py
import asyncio
import io
import re
import time
import discord
from discord.ext import commands
import random

import aiohttp

try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False

from config import admin_required, extra_help, GUILD_IDS
from data.DB.Storage.storage import get_levels, save_levels, get_xp, save_xp, log_activity

COOLDOWN_LEVEL = 30
COOLDOWN_LEADERBOARD = 30
GAME_XP_DEFAULT = True  # Eat It or Yeet It votes earn level XP unless toggled off
DAILY_COOLDOWN = 20 * 3600  # 20h between daily claims
DAILY_STREAK_WINDOW = 40 * 3600  # claim within 40h to keep the streak
DAILY_BASE = 50
DAILY_STREAK_BONUS = 10  # per streak day, capped below
DAILY_STREAK_CAP = 10


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


async def announce_level_up(guild, user_id, display_name, level, settings,
                          fallback_channel=None, accent=(88, 101, 242)):
    """Post a level-up message (custom template or default) with a celebration card."""
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
    text = render_levelup_message(settings, user_id, display_name, level)
    if _PIL_OK:
        try:
            member = guild.get_member(int(user_id))
            url = str(member.display_avatar.url) if member else None
            avatar_bytes = await _fetch_avatar_bytes(url) if url else None
            card = await asyncio.to_thread(
                build_levelup_card, avatar_bytes, display_name, level, accent)
            await channel.send(content=text, file=discord.File(card, filename="levelup.png"))
            return
        except Exception:
            pass
    try:
        await channel.send(text)
    except discord.HTTPException:
        pass


def render_levelup_message(settings, user_id, display_name, level):
    """Custom level-up template if set, otherwise the default message (fallback)."""
    template = settings.get("levelup_message")
    if not template:
        return f"🎉 <@{user_id}> leveled up to **{level}**!"
    return (template.replace("{user}", f"<@{user_id}>")
                   .replace("{name}", display_name)
                   .replace("{level}", str(level)))


async def _fetch_avatar_bytes(url):
    """Download an avatar image, returning None on any failure."""
    try:
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(str(url)) as resp:
                if resp.status == 200:
                    return await resp.read()
    except (aiohttp.ClientError, asyncio.TimeoutError):
        pass
    return None


def _hex_to_rgb(h):
    try:
        h = h.lstrip("#")
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, AttributeError, IndexError):
        return (88, 101, 242)


CARD_PRESETS = {
    "blurple": "5865F2", "green": "57F287", "yellow": "FEE75C",
    "orange": "E67E22", "red": "ED4245", "pink": "EB459E",
    "purple": "9B59B6", "teal": "1ABC9C", "white": "FFFFFF",
}


async def award_xp(guild, user_id, display_name, amount, fallback_channel=None,
                 apply_event=True):
    """Award XP, handling level-ups, role rewards, and announcements.

    Active XP events multiply earned XP (unless apply_event=False, used for
    manual admin grants). Returns the list of new levels reached.
    """
    gid, uid = str(guild.id), str(user_id)
    db = await get_levels(gid)
    settings = db.setdefault("settings", {})
    if apply_event:
        until = settings.get("xp_event_until", 0)
        if until and time.time() < until:
            amount = int(amount * settings.get("xp_event_multiplier", 2))
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
        for new_level in gained:
            await log_activity(uid, gid, "level_up", {"level": new_level})
        await apply_level_rewards(guild, user_id, user_data["level"], settings)
        accent = _hex_to_rgb(user_data.get("card_color", "#5865F2"))
        await announce_level_up(guild, user_id, display_name, user_data["level"],
                                settings, fallback_channel, accent)
    return gained


# ----- rank card -----

def _load_font(size, bold=False):
    names = (["arialbd.ttf", "arial.ttf", "DejaVuSans-Bold.ttf", "DejaVuSans.ttf"]
             if bold else ["arial.ttf", "DejaVuSans.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _fit_text(draw, text, font, max_width):
    if draw.textlength(text, font=font) <= max_width:
        return text
    while text and draw.textlength(text + "…", font=font) > max_width:
        text = text[:-1]
    return (text + "…") if text else "…"


def build_rank_card(avatar_bytes, username, level, xp, xp_needed, rank,
                    accent=(88, 101, 242)):
    """Render a 900x280 rank card PNG. Returns a BytesIO ready to send."""
    W, H = 900, 280
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(bg_mask).rounded_rectangle([0, 0, W, H], radius=24, fill=255)
    img.paste(Image.new("RGBA", (W, H), (35, 36, 40, 255)), (0, 0), bg_mask)
    d = ImageDraw.Draw(img)

    # avatar (circle)
    AV, ax, ay = 200, 40, 40
    av = None
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((AV, AV), Image.LANCZOS)
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (AV, AV), accent + (255,))
    circle = Image.new("L", (AV, AV), 0)
    ImageDraw.Draw(circle).ellipse([0, 0, AV, AV], fill=255)
    img.paste(av, (ax, ay), circle)

    font_big = _load_font(44, bold=True)
    font_med = _load_font(30, bold=True)
    font_small = _load_font(26)

    d.text((280, 48), _fit_text(d, username, font_big, 470), font=font_big,
           fill=(255, 255, 255, 255))
    rank_txt = f"RANK #{rank}" if rank else "UNRANKED"
    d.text((W - 40 - d.textlength(rank_txt, font=font_med), 60), rank_txt,
           font=font_med, fill=(181, 186, 193, 255))
    d.text((280, 108), f"LEVEL {level}", font=font_med, fill=accent + (255,))

    # progress bar
    bx, by, bw, bh = 280, 170, 580, 34
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=17, fill=(30, 31, 34, 255))
    frac = min(max(xp / xp_needed, 0), 1) if xp_needed else 0
    fw = int(bw * frac)
    if fw > 0:
        fill = Image.new("RGBA", (fw, bh), accent + (255,))
        fmask = Image.new("L", (fw, bh), 0)
        ImageDraw.Draw(fmask).rounded_rectangle([0, 0, fw, bh], radius=17, fill=255)
        img.paste(fill, (bx, by), fmask)
    d.text((bx, by + bh + 8), f"{xp:,} / {xp_needed:,} XP", font=font_small,
           fill=(181, 186, 193, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out


def build_levelup_card(avatar_bytes, username, level, accent=(88, 101, 242)):
    """Render a 900x320 LEVEL UP celebration card PNG."""
    W, H = 900, 320
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    bg_mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(bg_mask).rounded_rectangle([0, 0, W, H], radius=24, fill=255)
    img.paste(Image.new("RGBA", (W, H), (35, 36, 40, 255)), (0, 0), bg_mask)
    d = ImageDraw.Draw(img)

    # confetti
    rnd = random.Random(f"{username}-{level}")
    confetti = [(88, 101, 242), (87, 242, 135), (254, 231, 92),
                (237, 66, 69), (235, 69, 158), (230, 126, 34)]
    for _ in range(70):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        c = rnd.choice(confetti) + (255,)
        r = rnd.randint(3, 7)
        if rnd.random() < 0.5:
            d.ellipse([x - r, y - r, x + r, y + r], fill=c)
        else:
            d.rectangle([x - r, y - r, x + r, y + r], fill=c)

    # avatar (circle)
    AV, ax, ay = 180, 50, 70
    av = None
    if avatar_bytes:
        try:
            av = Image.open(io.BytesIO(avatar_bytes)).convert("RGBA")
            av = av.resize((AV, AV), Image.LANCZOS)
        except Exception:
            av = None
    if av is None:
        av = Image.new("RGBA", (AV, AV), accent + (255,))
    circle = Image.new("L", (AV, AV), 0)
    ImageDraw.Draw(circle).ellipse([0, 0, AV, AV], fill=255)
    img.paste(av, (ax, ay), circle)

    font_big = _load_font(64, bold=True)
    font_med = _load_font(40, bold=True)
    d.text((270, 55), "LEVEL UP!", font=font_big, fill=accent + (255,))
    d.text((270, 140), _fit_text(d, username, font_med, 560), font=font_med,
           fill=(255, 255, 255, 255))
    d.text((270, 195), f"LEVEL {level}", font=_load_font(54, bold=True),
           fill=(255, 255, 255, 255))

    out = io.BytesIO()
    img.save(out, format="PNG")
    out.seek(0)
    return out

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
        if str(message.channel.id) in settings.get("no_xp_channels", []):
            return  # this channel is opted out of XP
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

    @commands.slash_command(name="set_xp_rate", description="Set XP gain range per message", guild_ids=GUILD_IDS)
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

    @commands.slash_command(name="set_cooldown", description="Set XP gain cooldown (sec)", guild_ids=GUILD_IDS)
    @extra_help("Set the cooldown in seconds between XP gains per user. Set to 0 for no cooldown.")
    @admin_required()
    async def set_cooldown(self, interaction, seconds: int):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["cooldown"] = seconds
        await save_levels(gid, db)
        await interaction.respond(f"✅ Cooldown set to {seconds}s")

    @commands.slash_command(name="set_level_channel", description="Set level-up message channel", guild_ids=GUILD_IDS)
    @extra_help("Set the channel where level-up messages will be posted.")
    @admin_required()
    async def set_level_channel(self, interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["levelup_channel_id"] = str(channel.id)
        await save_levels(gid, db)
        await interaction.respond(f"✅ Level-up messages will post in {channel.mention}")

    @commands.slash_command(name="level", description="Check your or another user's level", guild_ids=GUILD_IDS)
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
        xp_needed = level * 100
        progress = self.calculate_level_progress(xp, level)
        progress_bar = self.create_progress_bar(progress, length=12)

        users = {k: v for k, v in db.items()
                 if k != "settings" and isinstance(v, dict) and "level" in v}
        ordered = sorted(users.items(),
                         key=lambda kv: (kv[1]["level"], kv[1].get("xp", 0)),
                         reverse=True)
        rank = next((i for i, (k, _) in enumerate(ordered, 1) if k == uid), 0)

        role_color = getattr(target, "color", None)
        color = (role_color if role_color and role_color != discord.Color.default()
                 else discord.Color.blurple())

        embed = discord.Embed(color=color)
        embed.set_author(name=target.display_name, icon_url=target.display_avatar.url)
        embed.set_thumbnail(url=target.display_avatar.url)
        rank_txt = f"Rank **#{rank}** of {len(ordered)}" if rank else "Unranked"
        embed.description = (
            f"# Level {level}\n"
            f"{rank_txt}\n\n"
            f"{progress_bar} {progress:.0f}%\n"
            f"**{xp:,}** / {xp_needed:,} XP  •  {xp_needed - xp:,} XP to level {level + 1}"
        )
        settings = db.get("settings", {})
        upcoming = sorted((int(lvl), rid)
                          for lvl, rid in settings.get("level_roles", {}).items()
                          if int(lvl) > level)
        if upcoming:
            embed.add_field(name="🎁 Next reward",
                            value=f"<@&{upcoming[0][1]}> at level {upcoming[0][0]}",
                            inline=False)
        streak = user.get("daily_streak", 0)
        if streak >= 2:
            embed.set_footer(text=f"🔥 {streak}-day daily streak — use /daily to keep it going")

        await interaction.followup.send(embed=embed)

    @commands.slash_command(name="leaderboard", description="Show XP leaderboard", guild_ids=GUILD_IDS)
    @extra_help("View the top 10 users by level and XP in this server.")
    async def leaderboard(self, interaction):
        await interaction.response.defer()
        gid = str(interaction.guild.id)
        me = str(interaction.user.id)

        now = time.time()
        last = self.cooldowns_lb.setdefault(gid, {}).get(me, 0)
        if now - last < COOLDOWN_LEADERBOARD:
            return await interaction.followup.send(f"⏳ Try again in {round(COOLDOWN_LEADERBOARD - (now - last), 1)}s!")
        self.cooldowns_lb[gid][me] = now

        db = await get_levels(gid)
        user_data = {k: v for k, v in db.items() if k != "settings"}
        top = sorted(user_data.items(),
                     key=lambda i: (i[1].get("level", 1), i[1].get("xp", 0)),
                     reverse=True)[:10]

        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, (uid, d) in enumerate(top, 1):
            member = interaction.guild.get_member(int(uid))
            name = member.display_name if member else d.get("username", f"User ID {uid}")
            pos = medals[i - 1] if i <= 3 else f"`{i}.`"
            you = " ⬅ you" if uid == me else ""
            lines.append(f"{pos} **{name}** — Level {d.get('level', 1)} · {d.get('xp', 0):,} XP{you}")

        embed = discord.Embed(title="🏆 XP Leaderboard", color=discord.Color.gold(),
                              description="\n".join(lines) or "No one has earned XP yet!")
        if user_data:
            embed.set_footer(text=f"{len(user_data)} members ranked")
        await interaction.followup.send(embed=embed)

    @commands.slash_command(name="add_xp", description="Add XP to a user", guild_ids=GUILD_IDS)
    @extra_help("Add XP to a user. Admins only. Level-ups are announced like normal.")
    @admin_required()
    async def add_xp(self, interaction, member: discord.Member, amount: int):
        if amount <= 0:
            return await interaction.respond(
                "Amount must be positive \u2014 use /resetxp to wipe someone's progress.",
                ephemeral=True)
        gained = await award_xp(interaction.guild, member.id, member.display_name,
                                amount, fallback_channel=interaction.channel,
                                apply_event=False)  # manual grants aren't multiplied
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

    @commands.slash_command(name="resetxp", description="Reset XP and level for a user", guild_ids=GUILD_IDS)
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

    @commands.slash_command(name="cleardata", description="Clear all level data for this server", guild_ids=GUILD_IDS)
    @extra_help("Clear all level data for this server. Admins only.")
    @admin_required()
    async def cleardata(self, interaction):
        await save_levels(str(interaction.guild.id), {})
        await interaction.respond("⚠️ All data cleared for this server.")

    @commands.slash_command(name="getxpsettings", description="View current XP settings", guild_ids=GUILD_IDS)
    @extra_help("View XP gain, cooldown, level-up channel, role rewards, no-XP channels, XP events, and the game XP toggle.")
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
        no_xp = settings.get("no_xp_channels", [])
        embed.add_field(name="🔇 No-XP Channels",
                        value=", ".join(f"<#{c}>" for c in no_xp) or "None",
                        inline=False)
        until = settings.get("xp_event_until", 0)
        if until and until > time.time():
            mult = settings.get("xp_event_multiplier", 2)
            embed.add_field(name="🎉 XP Event",
                            value=f"{mult}x until <t:{int(until)}:R>", inline=False)
        else:
            embed.add_field(name="🎉 XP Event", value="None active", inline=False)
        msg = settings.get("levelup_message")
        embed.add_field(name="📣 Level-up Message",
                        value=(msg[:100] + "…" if len(msg) > 100 else msg) if msg else "Default",
                        inline=False)

        await interaction.respond(embed=embed)

    @commands.slash_command(name="set_level_role", description="Set a role reward for reaching a level", guild_ids=GUILD_IDS)
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

    @commands.slash_command(name="remove_level_role", description="Remove a level role reward", guild_ids=GUILD_IDS)
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

    @commands.slash_command(name="toggle_no_xp", description="Toggle XP gains in a channel", guild_ids=GUILD_IDS)
    @extra_help("Turns message XP on/off for a channel. Useful for bot-spam channels.")
    @admin_required()
    async def toggle_no_xp(self, interaction, channel: discord.TextChannel):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        lst = db.setdefault("settings", {}).setdefault("no_xp_channels", [])
        cid = str(channel.id)
        if cid in lst:
            lst.remove(cid)
            await interaction.respond(f"✅ {channel.mention} will now earn XP.")
        else:
            lst.append(cid)
            await interaction.respond(f"🔇 {channel.mention} will no longer earn XP.")
        await save_levels(gid, db)

    @commands.slash_command(name="xp_event", description="Start a bonus XP event")
    @extra_help("Starts a server-wide XP multiplier event for the given minutes (multiplier 2-5).")
    @admin_required()
    async def xp_event(self, interaction, minutes: int,
                       multiplier: discord.Option(int, "XP multiplier (2-5)", default=2)):  # type: ignore
        if minutes < 1 or minutes > 1440:
            return await interaction.respond("Minutes must be between 1 and 1440.", ephemeral=True)
        if multiplier < 2 or multiplier > 5:
            return await interaction.respond("Multiplier must be between 2 and 5.", ephemeral=True)
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        settings["xp_event_until"] = time.time() + minutes * 60
        settings["xp_event_multiplier"] = multiplier
        await save_levels(gid, db)
        await interaction.respond(
            f"🎉 **{multiplier}x XP event** started for {minutes} minute{'s' if minutes != 1 else ''}!")

    @commands.slash_command(name="xp_event_end", description="End the bonus XP event early", guild_ids=GUILD_IDS)
    @extra_help("Ends a running XP event immediately.")
    @admin_required()
    async def xp_event_end(self, interaction):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        if settings.get("xp_event_until", 0) > time.time():
            settings["xp_event_until"] = 0
            await save_levels(gid, db)
            await interaction.respond("🎉 XP event ended.")
        else:
            await interaction.respond("No XP event is running.", ephemeral=True)

    @commands.slash_command(name="daily", description="Claim your daily XP bonus", guild_ids=GUILD_IDS)
    @extra_help("Claim XP once every 20 hours. Claiming on consecutive days builds a streak for bonus XP.")
    async def daily(self, interaction):
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        target = interaction.user
        db = await get_levels(gid)
        user = db.setdefault(uid, {"xp": 0, "level": 1, "username": target.display_name})
        now = time.time()
        last = user.get("daily_last", 0)
        if now - last < DAILY_COOLDOWN:
            wait = DAILY_COOLDOWN - (now - last)
            h, rem = divmod(int(wait), 3600)
            return await interaction.respond(
                f"⏳ Daily already claimed! Come back in {h}h {rem // 60}m.", ephemeral=True)
        streak = user.get("daily_streak", 0)
        streak = streak + 1 if now - last < DAILY_STREAK_WINDOW else 1
        amount = DAILY_BASE + min(streak, DAILY_STREAK_CAP) * DAILY_STREAK_BONUS
        user["daily_last"] = now
        user["daily_streak"] = streak
        await save_levels(gid, db)
        await log_activity(uid, gid, "daily_claim", {"streak": streak})
        gained = await award_xp(interaction.guild, target.id, target.display_name,
                                amount, fallback_channel=interaction.channel)
        msg = f"🎁 Daily claimed! **+{amount} XP** (🔥 {streak}-day streak)"
        if gained:
            msg += f"\n🎉 And that leveled you up to **{db[uid]['level']}**!"
        await interaction.respond(msg)

    @commands.slash_command(name="cardcolor", description="Set your rank card accent color", guild_ids=GUILD_IDS)
    @extra_help("Personalize your /rank card and level-up card with a hex color (e.g. #EB459E), a preset name, or 'reset'.")
    async def cardcolor(self, interaction, color: str):
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        db = await get_levels(gid)
        user = db.setdefault(uid, {"xp": 0, "level": 1,
                                   "username": interaction.user.display_name})
        c = color.strip().lower()
        if c in ("reset", "default"):
            user.pop("card_color", None)
            await save_levels(gid, db)
            return await interaction.respond("🎨 Card color reset to default.")
        if c in CARD_PRESETS:
            hexcode = CARD_PRESETS[c]
        else:
            m = re.match(r"^#?([0-9a-f]{6})$", c)
            if not m:
                presets = ", ".join(sorted(CARD_PRESETS))
                return await interaction.respond(
                    f"Give me a hex color like `#EB459E`, a preset ({presets}), or `reset`.",
                    ephemeral=True)
            hexcode = m.group(1).upper()
        user["card_color"] = "#" + hexcode
        await save_levels(gid, db)
        await interaction.respond(f"🎨 Card color set to `#{hexcode}`! Check it with /rank.")

    @commands.slash_command(name="set_levelup_message", description="Set a custom level-up message", guild_ids=GUILD_IDS)
    @extra_help("Set the level-up announcement text. Use {user} for a ping, {name} for the display name, {level} for the new level. Run with no text to reset to the default.")
    @admin_required()
    async def set_levelup_message(self, interaction, message: str = None):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        if not message:
            settings.pop("levelup_message", None)
            await save_levels(gid, db)
            return await interaction.respond("✅ Level-up message reset to default.")
        if len(message) > 300:
            return await interaction.respond("Keep it under 300 characters.", ephemeral=True)
        settings["levelup_message"] = message
        await save_levels(gid, db)
        preview = render_levelup_message(settings, interaction.user.id,
                                         interaction.user.display_name, 5)
        await interaction.respond(f"✅ Level-up message set! Preview:\n{preview}")

    @commands.slash_command(name="rank", description="Show your rank card", guild_ids=GUILD_IDS)
    @extra_help("Generates a rank card image with your level, XP progress, and server rank.")
    async def rank(self, interaction, member: discord.Member = None):
        await interaction.response.defer()
        target = member or interaction.user
        gid, uid = str(interaction.guild.id), str(target.id)
        db = await get_levels(gid)
        user = db.get(uid)
        if not user:
            return await interaction.followup.send("No level data found for that user.")
        users = {k: v for k, v in db.items()
                 if k != "settings" and isinstance(v, dict) and "level" in v}
        ordered = sorted(users.items(), key=lambda kv: (kv[1]["level"], kv[1].get("xp", 0)),
                         reverse=True)
        rank = next((i for i, (k, _) in enumerate(ordered, 1) if k == uid), 0)
        level = user.get("level", 1)
        xp = user.get("xp", 0)
        xp_needed = level * 100

        if not _PIL_OK:
            embed = discord.Embed(title="📊 Rank", color=discord.Color.blue())
            embed.set_author(name=target.display_name)
            embed.add_field(name="Rank", value=f"#{rank}" if rank else "Unranked", inline=True)
            embed.add_field(name="Level", value=level, inline=True)
            embed.add_field(name="XP", value=f"{xp}/{xp_needed}", inline=True)
            return await interaction.followup.send(embed=embed)

        avatar_bytes = await _fetch_avatar_bytes(target.display_avatar.url)
        accent = _hex_to_rgb(user.get("card_color", "#5865F2"))
        card = await asyncio.to_thread(
            build_rank_card, avatar_bytes, target.display_name, level, xp, xp_needed,
            rank, accent)
        await interaction.followup.send(file=discord.File(card, filename="rank.png"))

def setup(client):
    client.add_cog(LevelSystem(client))
