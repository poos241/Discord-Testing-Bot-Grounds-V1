# cogs/level_system.py
import asyncio
import io
import re
import time
from contextlib import asynccontextmanager
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
from data.DB.db import database
from data.DB.Storage.storage import (
    get_levels, save_levels, get_xp, save_xp, log_activity,
    get_voice_xp_config,
)

COOLDOWN_LEVEL = 30
COOLDOWN_LEADERBOARD = 30
GAME_XP_DEFAULT = True  # Eat It or Yeet It votes earn level XP unless toggled off
DAILY_COOLDOWN = 20 * 3600  # 20h between daily claims
DAILY_STREAK_WINDOW = 40 * 3600  # claim within 40h to keep the streak
DAILY_BASE = 50
DAILY_STREAK_BONUS = 10  # per streak day, capped below
DAILY_STREAK_CAP = 10

# P2-15: cap on the /set_level_role backfill. A reward configured
# after members already passed its level is granted to them on the
# spot, but each grant is a Discord call, so one invocation backfills
# at most this many members and tells the admin how many are left
# (re-run the command to continue) instead of holding the
# interaction open for a whole server.
BACKFILL_MAX = 100

# P2-5: cap on the per-message XP range. /set_xp_rate used to accept any
# maximum, so an xp_max of 10**9 was storable and every message became
# a multi-level event. The command refuses anything above this, and
# on_message clamps stored values too, so bad data saved before the
# cap existed can't keep awarding huge XP either.
XP_RATE_MAX = 100

# P2-6: cap on the per-message XP cooldown. /set_cooldown used to store
# `seconds` verbatim, so a negative value was storable and every message
# earned XP -- `now - ts < cooldown` is False for any negative cooldown,
# so the cooldown was off while settings claimed e.g. -30s. The command
# refuses anything outside 0..3600, and on_message clamps stored values
# too, so bad data saved before the cap existed can't keep disabling
# the cooldown either.
COOLDOWN_MAX = 3600

# P1-18: a Postgres advisory lock per guild serializes every
# read-modify-write on that guild's level blob. get_levels +
# save_levels is a whole-blob fetch + upsert with no lock, so two
# concurrent messages (or a message racing a game/voice/bridge/panel
# grant) used to interleave between the read and the write and the
# last writer silently discarded the other's XP and level-up.
#
# The lock is pg_advisory_xact_lock(hashtext("levels:<guild_id>")),
# taken inside a transaction on the shared async database
# connection. It works even when no levels row exists yet (the key
# is derived from the guild id, not from a row), and it serialises
# across PROCESSES -- the main bot and the Havenly Helper worker
# share the database, so a single-process asyncio.Lock can no
# longer protect the blob. The lock is held only across the
# load -> mutate -> save itself, never across Discord calls
# (announcements, role adds), so a slow level-up DM can't stall the
# guild's other XP.
#
# The transaction is the lock's scope: the advisory lock is released
# automatically at COMMIT/ROLLBACK, and the load + save ride in the
# same transaction, so the whole read-modify-write is atomic.
# Never nest get_level_lock: a caller that already holds it must
# use _apply_xp_locked(), never award_xp() -- the nested
# transaction would degrade to a savepoint under the same lock,
# which is safe but pointless, and the discipline keeps the lock
# scope obvious.


@asynccontextmanager
async def get_level_lock(guild_id):
    """Async context manager holding one guild's level lock.

    Use as ``async with get_level_lock(gid):`` around a load ->
    mutate -> save. Same call shape as before (the call sites are
    unchanged); the context itself is the lock, so nothing is
    yielded.
    """
    key = "levels:%s" % str(guild_id)
    async with database.transaction():
        await database.execute(
            "SELECT pg_advisory_xact_lock(hashtext(:key)::bigint)",
            {"key": key},
        )
        yield


async def game_xp_enabled(guild_id):
    """Whether game votes earn level XP (per-server toggle, default on)."""
    db = await get_levels(str(guild_id))
    return db.get("settings", {}).get("game_xp", GAME_XP_DEFAULT)


async def levels_enabled(guild_id):
    """Whether the level system is on for this server (default OFF).

    The system starts off; an admin turns it on with /toggle_levels.
    When off, no XP is earned from messages, games, voice, or manual
    grants, and no level-up messages are sent."""
    db = await get_levels(str(guild_id))
    return bool(db.get("settings", {}).get("levels_enabled", False))


async def sync_level_rewards(guild, user_id, level, settings):
    """Reconcile a member's level-role rewards with their current level.

    Adds every reward for a level the member has reached that they
    don't hold yet, and removes every configured reward for a level
    above theirs that they still hold (level-down, panel Remove XP,
    or a reward re-pointed at a higher level). One Discord call per
    role, so a role the bot can't manage (e.g. sitting above the
    bot, where add/remove raises Forbidden) fails on its own and
    never blocks the other roles.

    Returns (added, removed, failed): role names added, role names
    removed, and "Name (reason)" strings for the roles that could
    not be added or removed. Never raises; a member who left the
    server, or a server with no rewards configured, returns three
    empty lists. Failures are also logged loudly, because a reward
    the bot can't grant looks live to an admin until someone
    notices the role never lands. (P2-15: apply_level_rewards used
    to only ever add, and swallowed Forbidden per role, so a member
    who lost levels kept the roles and a reward above the bot
    failed silently.)
    """
    rewards = (settings or {}).get("level_roles", {})
    if not rewards:
        return [], [], []
    member = guild.get_member(int(user_id))
    if member is None:
        return [], [], []
    should_have = set()
    for lvl_str, role_id in rewards.items():
        try:
            if level >= int(lvl_str):
                should_have.add(int(role_id))
        except (ValueError, TypeError):
            continue
    # Track holdings locally as we go: the member's cached role list
    # may not reflect a role we just added/removed, and the same role
    # can be configured at two levels, so a stale read would add or
    # remove it twice.
    held = {role.id for role in member.roles}
    added, removed, failed = [], [], []
    for lvl_str, role_id in rewards.items():
        try:
            rid = int(role_id)
            role = guild.get_role(rid)
        except (ValueError, TypeError):
            continue
        if role is None:
            print("[WARN] Level reward for level %s points at deleted "
                  "role %s; no member can ever earn it."
                  % (lvl_str, role_id))
            continue
        try:
            if rid in should_have and rid not in held:
                await member.add_roles(
                    role, reason="Level reward: reached level %s" % lvl_str)
                held.add(rid)
                added.append(role.name)
            elif rid not in should_have and rid in held:
                await member.remove_roles(
                    role, reason="Level reward: below level %s" % lvl_str)
                held.discard(rid)
                removed.append(role.name)
        except discord.Forbidden:
            failed.append("%s (bot can't manage this role -- it may sit "
                          "above the bot or the bot lacks Manage Roles)"
                          % role.name)
            print("[WARN] Could not %s level reward %s for %s: Forbidden "
                  "(role above the bot or missing Manage Roles)."
                  % ("grant" if rid in should_have else "remove",
                     role.name, member.display_name))
        except discord.HTTPException as exc:
            failed.append("%s (%s)" % (role.name, exc))
            print("[WARN] Could not sync level reward %s for %s: %r"
                  % (role.name, member.display_name, exc))
    return added, removed, failed


async def apply_level_rewards(guild, user_id, level, settings):
    """Grant level-role rewards the member has earned (cumulative).

    Thin wrapper around sync_level_rewards: on a level-up the sync
    only ever adds (nothing is above the new level), and any role
    the bot can't grant is logged loudly by the sync instead of
    being swallowed here. Kept so existing callers keep working.
    (P2-15)"""
    await sync_level_rewards(guild, user_id, level, settings)


async def remove_level_rewards(guild, user_id, settings):
    """Remove every configured level-role reward the member currently holds.

    Mirror of apply_level_rewards for resets / level-downs: collects the
    reward roles the member actually has and removes them in one call.
    Returns (removed, failed): the names of the roles taken away, and
    the names of the ones that could not be removed (e.g. a reward role
    sitting above the bot, where remove_roles raises Forbidden -- a
    subclass of HTTPException -- so the whole call fails and nothing
    was removed). A failure never raises; the caller reports the
    failed names so an admin can remove them by hand. A member who
    left the server, or who holds no reward roles, returns two empty
    lists. (P2-7: /resetxp used to leave every reward role on the
    member, so a reset member kept roles they no longer qualified
    for. The wider backfill/hierarchy work is P2-15, not this item.)
    """
    rewards = settings.get("level_roles", {})
    if not rewards:
        return [], []
    member = guild.get_member(int(user_id))
    if member is None:
        return [], []
    roles = []
    for lvl_str, role_id in rewards.items():
        try:
            role = guild.get_role(int(role_id))
        except (ValueError, TypeError):
            continue
        if role is not None and role in member.roles:
            roles.append(role)
    if not roles:
        return [], []
    try:
        await member.remove_roles(
            *roles, reason="Level reset: removing earned level-role rewards")
    except discord.HTTPException:
        return [], [role.name for role in roles]
    return [role.name for role in roles], []


async def announce_level_up(guild, user_id, display_name, level, settings,
                          fallback_channel=None, accent=(88, 101, 242),
                          interaction=None):
    """Post a level-up message (custom template or default) with a celebration card.

    Delivery, in order:
    1. A level-up channel is set: post there (public by design -- the
       admin chose that channel as the celebration spot).
    2. No level channel, and the XP came from a slash command: send the
       announcement as an EPHEMERAL followup to that interaction, so
       only the person who invoked the command sees it.
    3. No level channel and no interaction (message or voice XP): stay
       silent -- a bot cannot send an ephemeral message without an
       interaction to answer, and public posts and DMs are both out.
       The XP and role rewards still apply.

    `fallback_channel` is kept for callers that pass it but is no
    longer a delivery target (the public fallback post is what Emily
    rejected 2026-11-09). `interaction` is the slash-command
    interaction that caused the XP (None for message/voice XP).

    CALLERS MUST DEFER WITH ephemeral=True: a public defer locks the
    whole interaction's followups public, and Discord then ignores
    the ephemeral flag on the followup -- the card is sent with
    ephemeral=True but stored with flags=0 (live 2026-11-09, /add_xp
    level-up to 8). /daily and /add_xp both defer ephemeral.
    """
    channel = None
    channel_id = settings.get("levelup_channel_id")
    if channel_id:
        try:
            channel = guild.get_channel(int(channel_id))
        except (ValueError, TypeError):
            channel = None
    text = render_levelup_message(settings, user_id, display_name, level)
    text += ("\n\nDon't want level-up messages? Run /toggle_level_messages "
             "to turn them off -- you'll still earn XP.")
    if channel is None and interaction is not None:
        # Ephemeral followup: only the invoker sees it. A followup can
        # only be sent to an interaction that was deferred or answered
        # (/daily and /add_xp both defer first), and the followup token
        # stays valid for 15 minutes, so this cannot expire mid-award.
        if _PIL_OK:
            try:
                member = guild.get_member(int(user_id))
                url = str(member.display_avatar.url) if member else None
                avatar_bytes = await _fetch_avatar_bytes(url) if url else None
                card = await asyncio.to_thread(
                    build_levelup_card, avatar_bytes, display_name, level, accent)
                await interaction.followup.send(
                    content=text, file=discord.File(card, filename="levelup.png"),
                    ephemeral=True)
                return
            except Exception:
                pass
        try:
            await interaction.followup.send(text, ephemeral=True)
        except (discord.Forbidden, discord.HTTPException):
            # Interaction gone (or the followup failed) -- stay silent
            # rather than posting it publicly.
            pass
        return
    if channel is None:
        # No level channel and no interaction to answer: nowhere
        # private to send it, so skip the announcement quietly.
        return
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
    except (discord.Forbidden, discord.HTTPException):
        # Bot can't post there (no access, or the channel is gone).
        # The user just doesn't get the message.
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


def _apply_xp_to_db(db, user_id, display_name, amount, apply_event=True):
    """Mutate one user's XP inside an already-loaded levels blob.

    Pure in-memory work: no I/O, no lock (the caller owns both).
    Returns (gained_levels, user_data). user_data is None when the
    level system is off in this server (nothing was mutated).
    Split out of _apply_xp_locked so award_xp_batch() can apply
    several awards to one loaded blob (P2-8) instead of reloading
    and re-saving the whole blob per member.
    """
    uid = str(user_id)
    settings = db.setdefault("settings", {})
    if not settings.get("levels_enabled", False):
        return [], None  # level system is off in this server -- no XP at all
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
    return gained, user_data


async def _apply_xp_locked(guild, user_id, display_name, amount,
                         apply_event=True):
    """Load -> mutate -> save one user's XP. CALLER MUST HOLD the guild's
    level lock (see get_level_lock); never call this without it.

    Returns (gained_levels, user_data, settings). user_data is None
    when the level system is off in this server (nothing was saved).
    Kept separate from award_xp so the lock covers only the blob
    read/write and not the slow Discord calls that follow it.
    """
    gid, uid = str(guild.id), str(user_id)
    db = await get_levels(gid)
    gained, user_data = _apply_xp_to_db(db, uid, display_name, amount,
                                        apply_event)
    if user_data is None:
        return [], None, db.get("settings", {})
    await save_levels(gid, db)
    return gained, user_data, db["settings"]


async def award_xp(guild, user_id, display_name, amount, fallback_channel=None,
                 apply_event=True, interaction=None):
    """Award XP, handling level-ups, role rewards, and announcements.

    Active XP events multiply earned XP (unless apply_event=False, used for
    manual admin grants). Returns the list of new levels reached.

    P1-18: the blob read/write is serialized per guild (see
    get_level_lock), so concurrent grants can't lose each other's XP.
    Level-up announcements and role rewards run after the lock is
    released, so they can't stall other grants.

    `interaction` is the slash-command interaction that caused the XP
    (passed by /daily and /add_xp so the level-up can go out as an
    ephemeral followup when no level channel is set); None for
    message/voice XP.
    """
    gid, uid = str(guild.id), str(user_id)
    async with get_level_lock(gid):
        gained, user_data, settings = await _apply_xp_locked(
            guild, user_id, display_name, amount, apply_event)
    if not gained:
        return []
    for new_level in gained:
        await log_activity(uid, gid, "level_up", {"level": new_level})
    await apply_level_rewards(guild, user_id, user_data["level"], settings)
    # A user who opted out still earns XP (and role rewards) but
    # gets no level-up announcement, anywhere.
    if user_data.get("level_messages", True):
        accent = _hex_to_rgb(user_data.get("card_color", "#5865F2"))
        await announce_level_up(guild, user_id, display_name, user_data["level"],
                                settings, fallback_channel, accent,
                                interaction=interaction)
    return gained


async def award_xp_batch(guild, awards, fallback_channel=None,
                       apply_event=True, interaction=None):
    """Award level XP to several members with ONE levels-blob load/save.

    P2-8: the voice XP ticker used to call award_xp() once per member
    per 5-minute chunk, and every call re-loaded + re-saved the whole
    guild levels blob. Batching holds the guild lock once, loads the
    blob once, applies every award through _apply_xp_to_db(), and
    saves once; level-up announcements and role rewards still run
    per member afterwards, outside the lock, exactly as award_xp()
    does them. An XP event multiplies each award the same way
    award_xp() would (unless apply_event=False).

    `awards` is an iterable of (user_id, display_name, amount).
    Returns [(user_id, gained_levels), ...] in the order given.
    An empty list does no I/O at all. When the level system is off
    in this server nothing is awarded or saved.
    """
    awards = list(awards)
    if not awards:
        return []
    gid = str(guild.id)
    async with get_level_lock(gid):
        db = await get_levels(gid)
        settings = db.get("settings", {})
        if not settings.get("levels_enabled", False):
            return []
        results = []
        for user_id, display_name, amount in awards:
            gained, user_data = _apply_xp_to_db(
                db, user_id, display_name, amount, apply_event)
            if user_data is not None:
                results.append((str(user_id), display_name, gained, user_data))
        await save_levels(gid, db)
    out = []
    for user_id, display_name, gained, user_data in results:
        if not gained:
            out.append((user_id, []))
            continue
        for new_level in gained:
            await log_activity(user_id, gid, "level_up", {"level": new_level})
        await apply_level_rewards(guild, user_id, user_data["level"], settings)
        # A user who opted out still earns XP (and role rewards) but
        # gets no level-up announcement, anywhere.
        if user_data.get("level_messages", True):
            accent = _hex_to_rgb(user_data.get("card_color", "#5865F2"))
            await announce_level_up(guild, user_id, display_name,
                                    user_data["level"], settings,
                                    fallback_channel, accent,
                                    interaction=interaction)
        out.append((user_id, gained))
    return out


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


class NoXpBulkView(discord.ui.View):
    """Pick many channels at once and turn XP off (or back on) in all of them.

    Only the admin who opened it can use it. The channel picker holds
    the selection; Disable XP adds every picked channel to the server's
    no_xp_channels list, Enable XP removes them. One batch per opening.
    """

    def __init__(self, author_id, guild_id):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild_id = guild_id
        self.picked_ids = []

        channel_select = discord.ui.ChannelSelect(
            placeholder="Pick channels (up to 25)",
            min_values=1,
            max_values=25,
            channel_types=[discord.ChannelType.text],
        )
        channel_select.callback = self._on_channels
        self.channel_select = channel_select
        self.add_item(channel_select)

        disable_button = discord.ui.Button(
            label="Disable XP", style=discord.ButtonStyle.danger)
        disable_button.callback = self._on_disable
        self.add_item(disable_button)

        enable_button = discord.ui.Button(
            label="Enable XP", style=discord.ButtonStyle.success)
        enable_button.callback = self._on_enable
        self.add_item(enable_button)

        cancel_button = discord.ui.Button(
            label="Cancel", style=discord.ButtonStyle.grey)
        cancel_button.callback = self._on_cancel
        self.add_item(cancel_button)

    async def _check_author(self, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who opened this can use it.", ephemeral=True)
            return False
        return True

    async def _on_channels(self, interaction):
        if not await self._check_author(interaction):
            return
        self.picked_ids = [str(c.id) for c in self.channel_select.values]
        await interaction.response.defer(ephemeral=True)

    async def _on_disable(self, interaction):
        await self._apply(interaction, enable=False)

    async def _on_enable(self, interaction):
        await self._apply(interaction, enable=True)

    async def _on_cancel(self, interaction):
        if not await self._check_author(interaction):
            return
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            content="Cancelled -- no channels changed.", view=self)

    async def _apply(self, interaction, enable):
        if not await self._check_author(interaction):
            return
        if not self.picked_ids:
            await interaction.response.send_message(
                "Pick at least one channel first.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        db = await get_levels(str(self.guild_id))
        lst = db.setdefault("settings", {}).setdefault("no_xp_channels", [])
        mentions = []
        for cid in self.picked_ids:
            channel = (interaction.guild.get_channel(int(cid))
                       if interaction.guild else None)
            mentions.append(channel.mention if channel else "<#%s>" % cid)
        if enable:
            removed = [cid for cid in self.picked_ids if cid in lst]
            for cid in removed:
                lst.remove(cid)
            kept = len(self.picked_ids) - len(removed)
            summary = ("Enabled XP in %s (%d removed from no-XP%s)."
                       % (", ".join(mentions), len(removed),
                          "; %d weren't disabled" % kept if kept else ""))
        else:
            added = [cid for cid in self.picked_ids if cid not in lst]
            lst.extend(added)
            already = len(self.picked_ids) - len(added)
            summary = ("Disabled XP in %s (%d added to no-XP%s)."
                       % (", ".join(mentions), len(added),
                          "; %d were already disabled" % already if already else ""))
        await save_levels(str(self.guild_id), db)
        for item in self.children:
            item.disabled = True
        await interaction.edit_original_response(content=summary, view=self)


def _chunk_lines(lines, limit=1000):
    """Split lines into chunks of at most `limit` chars, never splitting
    mid-line. Same shape as the help cog's chunker (embed field values
    cap at 1024). A single line longer than the limit is truncated."""
    chunks, current = [], ""
    for line in lines:
        if len(line) > limit:
            line = line[:limit - 1] + "…"
        if current and len(current) + 1 + len(line) > limit:
            chunks.append(current)
            current = line
        else:
            current = (current + "\n" + line) if current else line
    if current:
        chunks.append(current)
    return chunks


def _build_level_embeds(sections):
    """Turn [(title, description, [(field name, field value), ...]), ...]
    into a list of embeds, each within Discord's caps (25 fields,
    ~5800 chars total). Each section starts a fresh embed; a section
    whose fields don't fit continues in following embeds titled
    "<title> (cont.)"."""
    embeds = []
    for title, description, fields in sections:
        current = None

        def _size(embed):
            total = len(embed.title or "") + len(embed.description or "")
            return total + sum(len(f.name) + len(f.value) for f in embed.fields)

        for name, value in fields:
            if (current is None or len(current.fields) >= 25
                    or _size(current) + len(name) + len(value) > 5800):
                current = discord.Embed(
                    title=(title if current is None else title + " (cont.)"),
                    color=discord.Color.blue())
                if description and current.title == title:
                    current.description = description
                embeds.append(current)
            current.add_field(name=name, value=value, inline=False)
        if current is None:
            # A section with no fields still gets its embed (its
            # description carries the content, e.g. "None — ...").
            current = discord.Embed(title=title, color=discord.Color.blue())
            if description:
                current.description = description
            embeds.append(current)
    return embeds


class LevelSettingsView(discord.ui.View):
    """The Manage button on the /level_settings overview. Only the
    admin who ran the overview can open the no-XP picker; the picker
    itself (NoXpBulkView) re-checks the opener on every click, so a
    stale view can't be driven by anyone else either."""

    def __init__(self, author_id, guild_id):
        super().__init__(timeout=300)
        self.author_id = author_id
        self.guild_id = guild_id

    @discord.ui.button(label="Manage no-XP channels",
                       style=discord.ButtonStyle.primary)
    async def manage(self, button, interaction):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the admin who ran /level_settings can use this.",
                ephemeral=True)
            return
        view = NoXpBulkView(self.author_id, self.guild_id)
        await interaction.response.send_message(
            content=("Pick channels below, then hit **Disable XP** to stop XP in all of them, "
                     "or **Enable XP** to turn XP back on in them."),
            view=view,
            ephemeral=True)


class CleardataConfirmView(discord.ui.View):
    """Confirm /cleardata before anything is wiped.

    One tap used to delete every member's XP/levels/streaks *and* the
    server settings (XP rate, cooldown, role rewards, no-XP channels,
    the levels_enabled flag itself), so a misclick silently turned the
    level system off. Confirm re-checks the cleardata gate at click
    time, reloads the levels row fresh, wipes only the member entries,
    and writes the row back with the settings preserved. A denied
    click leaves the view open so another admin can still confirm.
    """

    def __init__(self, guild_id):
        super().__init__(timeout=180)
        self.guild_id = str(guild_id)
        self.done = False

    @discord.ui.button(label="Yes, clear all level data",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction):
        if self.done:
            await interaction.response.send_message(
                "This confirmation was already handled.", ephemeral=True)
            return
        self.done = True
        from utils.permissions import check_interaction_permission, _default_admin_only
        if not await check_interaction_permission(
                interaction, "cleardata", _default_admin_only):
            self.done = False
            return
        for child in self.children:
            child.disabled = True
        try:
            db = await get_levels(self.guild_id)
            settings = db.get("settings", {})
            count = len([k for k in db if k != "settings"])
            await save_levels(self.guild_id, {"settings": settings})
        except Exception as exc:
            await interaction.response.edit_message(
                content=("⚠️ Could not clear level data (database error: %s) — "
                         "nothing was changed. Try again in a moment." % exc),
                view=self)
            self.stop()
            return
        await interaction.response.edit_message(
            content=(f"✅ Cleared level data for **{count}** member(s). "
                     "Server settings were kept (XP rate, cooldown, role "
                     "rewards, no-XP channels, level system on/off)."),
            view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction):
        if self.done:
            await interaction.response.send_message(
                "This confirmation was already handled.", ephemeral=True)
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ Cancelled — nothing was cleared.", view=self)
        self.stop()


class ResetxpConfirmView(discord.ui.View):
    """Confirm /resetxp before one member's progress is wiped.

    One tap used to reset a member's XP/level with no confirmation,
    while leaving every level-role reward on them and silently
    dropping daily_streak, daily_last, card_color and level_messages
    from the row. Confirm re-checks the resetxp gate at click time,
    reloads the levels row fresh under the guild lock, resets only
    XP and level (the row is mutated in place, so the non-XP keys
    survive), strips the member's earned level-role rewards, and
    reports anything it could not remove. A denied click leaves the
    view open so another admin can still confirm.
    """

    def __init__(self, guild_id, user_id):
        super().__init__(timeout=180)
        self.guild_id = str(guild_id)
        self.user_id = str(user_id)
        self.done = False

    @discord.ui.button(label="Yes, reset their XP",
                       style=discord.ButtonStyle.danger)
    async def confirm(self, button, interaction):
        if self.done:
            await interaction.response.send_message(
                "This confirmation was already handled.", ephemeral=True)
            return
        self.done = True
        from utils.permissions import check_interaction_permission, _default_admin_only
        if not await check_interaction_permission(
                interaction, "resetxp", _default_admin_only):
            self.done = False
            return
        for child in self.children:
            child.disabled = True
        guild = interaction.guild
        member = (guild.get_member(int(self.user_id))
                  if guild is not None else None)
        name = "that member"
        try:
            # P1-18: hold the guild lock across the load -> mutate ->
            # save, never across the Discord role call below.
            async with get_level_lock(self.guild_id):
                db = await get_levels(self.guild_id)
                user = db.get(self.user_id)
                if not user:
                    await interaction.response.edit_message(
                        content="That member has no level data — nothing to reset.",
                        view=self)
                    self.stop()
                    return
                settings = db.get("settings", {})
                old_level = user.get("level", 1)
                old_xp = user.get("xp", 0)
                # Reset XP/level only: mutate the row in place so the
                # non-XP keys (daily streak, card color, level-up
                # message preference, ...) survive the reset instead
                # of being dropped by a dict replacement.
                user["xp"] = 0
                user["level"] = 1
                if member is not None:
                    user["username"] = member.display_name
                name = user.get("username") or name
                await save_levels(self.guild_id, db)
        except Exception as exc:
            await interaction.response.edit_message(
                content=("⚠️ Could not reset that member (database error: %s) — "
                         "nothing was changed. Try again in a moment." % exc),
                view=self)
            self.stop()
            return
        # Role removal runs after the lock is released (a Discord call,
        # never under the guild lock) and after the DB reset, so a
        # failed removal never un-does the reset: the row is reset and
        # the message says exactly which roles still need removing.
        removed, failed = await remove_level_rewards(
            guild, self.user_id, settings)
        parts = ["✅ Reset %s: level %d (%s XP) → level 1, 0 XP."
                 % (name, old_level, f"{old_xp:,}")]
        if removed:
            parts.append("Removed level-role reward(s): %s."
                         % ", ".join(removed))
        if failed:
            parts.append("⚠️ Could not remove: %s (a reward role may sit "
                         "above the bot — remove by hand)."
                         % ", ".join(failed))
        if member is None:
            parts.append("They are no longer in the server, so no roles "
                         "were checked.")
        parts.append("Daily streak, card color, and level-up message "
                     "preference were kept.")
        await interaction.response.edit_message(
            content="\n".join(parts), view=self)
        self.stop()

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, button, interaction):
        if self.done:
            await interaction.response.send_message(
                "This confirmation was already handled.", ephemeral=True)
            return
        self.done = True
        for child in self.children:
            child.disabled = True
        await interaction.response.edit_message(
            content="❌ Cancelled — nothing was reset.", view=self)
        self.stop()


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
        # P2-14: webhook messages have a non-bot author, so anyone able
        # to post through a webhook in a channel could farm message XP
        # with no user account sending anything. Ignore them entirely.
        if message.author.bot or message.webhook_id is not None or not message.guild:
            return

        gid = str(message.guild.id)
        uid = str(message.author.id)

        db = await get_levels(gid)
        settings = db.get("settings", {})
        if not settings.get("levels_enabled", False):
            return  # level system is off in this server
        if str(message.channel.id) in settings.get("no_xp_channels", []):
            return  # this channel is opted out of XP
        # Threads: a thread under a no-XP channel never earns XP, and
        # when XP in threads is off no thread message earns XP (covers
        # ticket threads from external ticket bots, discussion threads,
        # and forum posts -- thread ids are created on the fly, so they
        # can never be pre-listed in no_xp_channels). Default on, so
        # nothing changes until an admin flips it with /toggle_thread_xp.
        if isinstance(message.channel, discord.Thread):
            parent_id = getattr(message.channel, "parent_id", None)
            if (parent_id is not None
                    and str(parent_id) in settings.get("no_xp_channels", [])):
                return
            if not settings.get("xp_in_threads", True):
                return
        cooldown = settings.get("cooldown", 0)
        # P2-6: clamp stored values saved before the /set_cooldown cap.
        # A negative cooldown used to make `now - ts < cooldown` False
        # for every message, so the cooldown was silently off.
        cooldown = max(0, min(cooldown, COOLDOWN_MAX))

        now = time.time()
        if cooldown:
            # P1-18 / P2-13: the cooldown check-then-save is a race too --
            # two messages at once both read the old timestamp and both
            # award. Hold the guild lock across the claim, then release
            # it before award_xp (which takes the lock itself).
            async with get_level_lock(gid):
                timestamps = await get_xp(gid)
                if now - timestamps.get(uid, 0) < cooldown:
                    return
                timestamps[uid] = now
                await save_xp(gid, timestamps)

        lo, hi = settings.get("xp_min", 1), settings.get("xp_max", 5)
        if lo > hi:  # guard against bad data saved before validation existed
            lo, hi = hi, lo
        # P2-5: clamp stored values saved before the /set_xp_rate cap.
        lo, hi = min(lo, XP_RATE_MAX), min(hi, XP_RATE_MAX)
        xp_gain = random.randint(lo, hi)

        await award_xp(message.guild, message.author.id, message.author.display_name,
                       xp_gain, fallback_channel=message.channel)

    @commands.slash_command(name="set_xp_rate", description="Set XP gain range per message", guild_ids=GUILD_IDS)
    @extra_help("Set the minimum and maximum XP that can be gained per message (maximum 100).")
    async def set_xp_rate(self, interaction, minimum: int, maximum: int):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "set_xp_rate", _default_admin_only):
            return
        if minimum < 0 or maximum < 0:
            return await interaction.respond("XP values can't be negative.", ephemeral=True)
        if minimum > maximum:
            return await interaction.respond("Minimum can't be higher than maximum.", ephemeral=True)
        # P2-5: no upper bound used to let xp_max of 10**9 be stored,
        # turning every message into a multi-level event.
        if maximum > XP_RATE_MAX:
            return await interaction.respond(
                "Maximum XP per message can't be more than %d." % XP_RATE_MAX,
                ephemeral=True)
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["xp_min"] = minimum
        db["settings"]["xp_max"] = maximum
        await save_levels(gid, db)
        await interaction.respond(f"✅ XP gain range set to {minimum}–{maximum} XP/msg")

    @commands.slash_command(name="set_cooldown", description="Set XP gain cooldown (sec)", guild_ids=GUILD_IDS)
    @extra_help("Set the cooldown in seconds between XP gains per user (0-3600). Set to 0 for no cooldown.")
    async def set_cooldown(self, interaction, seconds: int):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "set_cooldown", _default_admin_only):
            return
        # P2-6: a negative cooldown used to be stored verbatim, silently
        # disabling the cooldown (every message earned XP), and a huge
        # one could lock XP out for effectively forever.
        if seconds < 0:
            return await interaction.respond(
                "Cooldown can't be negative -- use 0 for no cooldown.",
                ephemeral=True)
        if seconds > COOLDOWN_MAX:
            return await interaction.respond(
                "Cooldown can't be more than %d seconds (1 hour)." % COOLDOWN_MAX,
                ephemeral=True)
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        db.setdefault("settings", {})["cooldown"] = seconds
        await save_levels(gid, db)
        await interaction.respond(f"✅ Cooldown set to {seconds}s")

    @commands.slash_command(name="set_level_channel", description="Set or remove the level-up message channel", guild_ids=GUILD_IDS)
    @extra_help("Set the channel where level-up messages will be posted, or turn remove on to clear it (level-ups then go out as ephemeral replies where possible, and are skipped otherwise).")
    async def set_level_channel(
        self,
        interaction,
        channel: discord.Option(discord.TextChannel, "Channel for level-up messages", required=False, default=None),
        remove: discord.Option(bool, "Remove the level-up channel", required=False, default=False),
    ):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "set_level_channel", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        if remove and channel is not None:
            return await interaction.respond(
                "Pick one: give a channel to set it, or turn remove on to clear it — not both.",
                ephemeral=True)
        if remove:
            settings.pop("levelup_channel_id", None)
            await save_levels(gid, db)
            return await interaction.respond(
                "✅ Level-up channel removed — level-ups will go out as ephemeral replies where possible, and are skipped otherwise.")
        if channel is None:
            current = settings.get("levelup_channel_id")
            return await interaction.respond(
                "Give a channel to set it, or turn remove on to clear it." +
                (f" Current channel: <#{current}>." if current else " No level-up channel is set right now."),
                ephemeral=True)
        settings["levelup_channel_id"] = str(channel.id)
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
    async def add_xp(self, interaction, member: discord.Member, amount: int):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "add_xp", _default_admin_only):
            return
        if amount <= 0:
            return await interaction.respond(
                "Amount must be positive \u2014 use /resetxp to wipe someone's progress.",
                ephemeral=True)
        if not await levels_enabled(interaction.guild.id):
            return await interaction.respond(
                "The level system is off in this server. Turn it on with /toggle_levels first.",
                ephemeral=True)
        # Defer first: award_xp can take seconds when it levels the
        # member up (role rewards + level-up card + announcement), and
        # an interaction left unanswered for 3s expires -- Discord
        # then shows "The application did not respond" even though the
        # XP was already awarded (live 10062 on 2026-11-09).
        # The defer MUST be ephemeral: a public defer locks the whole
        # interaction's followups public, and Discord then ignores the
        # ephemeral flag on the level-up followup (live 2026-11-09:
        # the card was sent with ephemeral=True but stored flags=0).
        # Everything on this interaction -- the level-up card AND the
        # confirmation below -- renders ephemeral, visible only to the
        # admin who ran the command.
        await interaction.response.defer(ephemeral=True)
        gained = await award_xp(interaction.guild, member.id, member.display_name,
                                amount, fallback_channel=interaction.channel,
                                apply_event=False,  # manual grants aren't multiplied
                                interaction=interaction)  # level-up goes ephemeral to the invoker
        db = await get_levels(str(interaction.guild.id))
        user_data = db[str(member.id)]
        xp_needed = user_data["level"] * 100
        if gained:
            await interaction.followup.send(
                f"\u2705 Added {amount} XP to {member.mention} \u2014 they leveled up to "
                f"**{user_data['level']}**! \U0001f389")
        else:
            xp_remaining = xp_needed - user_data["xp"]
            await interaction.followup.send(
                f"\u2705 Added {amount} XP to {member.mention}\n"
                f"\U0001f4c8 Level: {user_data['level']} \u2014 XP: {user_data['xp']}/{xp_needed} "
                f"(\U0001f9ee {xp_remaining} XP to next level)"
            )

    @commands.slash_command(name="resetxp", description="Reset XP and level for a user", guild_ids=GUILD_IDS)
    @extra_help("Reset a user's XP and level to 0 and 1 respectively. Admins only. Asks for confirmation first; the member's level-role rewards are removed too, while their daily streak, card color, and level-up message preference are kept.")
    async def resetxp(self, interaction, member: discord.Member):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "resetxp", _default_admin_only):
            return
        gid, uid = str(interaction.guild.id), str(member.id)
        db = await get_levels(gid)

        if uid not in db:
            await interaction.respond("User not found.")
            return
        # P2-7: one tap used to wipe the member's progress on the
        # spot, keep every level-role reward on them, and drop the
        # non-XP keys from the row. Now the reset asks first, strips
        # the earned reward roles on confirm, and keeps the rest of
        # the row (daily streak, card color, level-up message
        # preference) intact.
        user = db[uid]
        rewards = db.get("settings", {}).get("level_roles", {})
        held = []
        for lvl_str, role_id in rewards.items():
            try:
                role = interaction.guild.get_role(int(role_id))
            except (ValueError, TypeError):
                continue
            if role is not None and role in member.roles:
                held.append(role.name)
        prompt = (f"⚠️ Reset **{member.display_name}** (level "
                  f"{user.get('level', 1)}, {user.get('xp', 0):,} XP) back to "
                  "level 1, 0 XP?\n")
        if held:
            prompt += ("This also removes their level-role reward(s): %s.\n"
                       % ", ".join(held))
        prompt += ("Their daily streak, card color, and level-up message "
                   "preference are kept.")
        await interaction.respond(
            prompt, view=ResetxpConfirmView(gid, uid), ephemeral=True)

    @commands.slash_command(name="cleardata", description="Clear all level data for this server", guild_ids=GUILD_IDS)
    @extra_help("Clear every member's level data for this server. Admins only. Asks for confirmation first; server settings (XP rate, cooldown, role rewards, no-XP channels, level system on/off) are kept.")
    async def cleardata(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "cleardata", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        member_count = len([k for k in db if k != "settings"])
        if member_count == 0:
            return await interaction.respond(
                "There is no level data to clear in this server.",
                ephemeral=True)
        await interaction.respond(
            f"⚠️ Clear level data for **{member_count}** member(s)?\n"
            "This deletes every member's XP, levels, and daily streaks. "
            "**Server settings are kept** — XP rate, cooldown, role rewards, "
            "no-XP channels, and the level system on/off state stay as they are.",
            view=CleardataConfirmView(gid),
            ephemeral=True)

    @commands.slash_command(name="getxpsettings", description="View current XP settings", guild_ids=GUILD_IDS)
    @extra_help("View XP gain, cooldown, level-up channel, role rewards, no-XP channels, XP events, and the game XP toggle.")
    async def getxpsettings(self, interaction):
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.get("settings", {})

        embed = discord.Embed(title="📊 XP Settings", color=discord.Color.blue())
        embed.add_field(name="📊 Level System",
                        value=("ON" if settings.get("levels_enabled", False)
                               else "OFF — turn it on with /toggle_levels"),
                        inline=False)
        embed.add_field(name="⏳ Cooldown", value=f"{settings.get('cooldown', 0)}s", inline=False)
        embed.add_field(name="📈 XP Gain", value=f"{settings.get('xp_min', 1)} - {settings.get('xp_max', 5)}", inline=False)
        channel_id = settings.get("levelup_channel_id")
        embed.add_field(name="📢 Level-up Channel",
                        value=(f"<#{channel_id}>" if channel_id
                               else "Not set (level-ups go out as ephemeral replies, or are skipped)"),
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

    @commands.slash_command(name="level_settings", description="Show the level system's full configuration", guild_ids=GUILD_IDS)
    @extra_help("Admin overview of the level system: on/off, XP rates, cooldown, level-up channel, role rewards, XP events, which channels earn XP and which don't, and whether threads earn XP. Includes a button to manage no-XP channels.")
    async def level_settings(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "level_settings", _default_admin_only):
            return
        guild = interaction.guild
        gid = str(guild.id)
        db = await get_levels(gid)
        settings = db.get("settings", {}) if isinstance(db, dict) else {}
        try:
            voice_cfg = await get_voice_xp_config(gid)
        except Exception:
            voice_cfg = {}

        enabled = bool(settings.get("levels_enabled", False))
        xp_min = settings.get("xp_min", 1)
        xp_max = settings.get("xp_max", 5)
        cooldown = settings.get("cooldown", 0)
        game_xp = settings.get("game_xp", GAME_XP_DEFAULT)
        xp_threads = settings.get("xp_in_threads", True)
        no_xp = list(settings.get("no_xp_channels", []) or [])
        no_xp_set = set(str(c) for c in no_xp)
        level_roles = settings.get("level_roles", {}) or {}

        # Section 1: the settings themselves.
        fields = [
            ("Status", "ON" if enabled
             else "OFF — turn it on with /toggle_levels"),
            ("XP per message", "%s–%s XP, cooldown %ss" % (xp_min, xp_max, cooldown)),
            ("XP in threads", ("ON — messages in threads earn XP" if xp_threads
                               else "OFF — messages in threads earn no XP")),
            ("Game XP", "ON" if game_xp else "OFF"),
        ]
        voice_on = voice_cfg.get("enabled", True)
        fields.append(("Voice XP",
                       ("ON — %s XP/min, cap %s/day"
                        % (voice_cfg.get("xp_per_minute", 1),
                           voice_cfg.get("daily_cap_xp", 100)))
                       if voice_on else "OFF"))
        channel_id = settings.get("levelup_channel_id")
        fields.append(("Level-up channel",
                       (f"<#{channel_id}>" if channel_id
                        else "Not set (level-ups go out as ephemeral replies, or are skipped)")))
        msg = settings.get("levelup_message")
        fields.append(("Level-up message",
                       ((msg[:100] + "…") if len(msg) > 100 else msg)
                       if msg else "Default"))
        until = settings.get("xp_event_until", 0)
        if until and until > time.time():
            fields.append(("XP event",
                           "%sx until <t:%d:R>"
                           % (settings.get("xp_event_multiplier", 2), int(until))))
        else:
            fields.append(("XP event", "None active"))
        if level_roles:
            lines = []
            for lvl in sorted(level_roles,
                              key=lambda s: int(s) if str(s).isdigit() else 0):
                try:
                    role = guild.get_role(int(level_roles[lvl]))
                except (ValueError, TypeError):
                    role = None
                lines.append("Level %s: %s"
                             % (lvl, role.mention if role is not None
                                else "(deleted role, id %s)" % level_roles[lvl]))
            fields.append(("Role rewards", "\n".join(lines)))
        else:
            fields.append(("Role rewards", "None set"))
        sections = [("Level System Settings", None, fields)]

        # Section 2: the no-XP channels, with names (deleted ones marked).
        if not no_xp:
            sections.append(("No-XP channels (0)",
                             "None — every text channel earns XP.", []))
        else:
            lines = []
            for cid in no_xp:
                channel = (guild.get_channel(int(cid))
                           if str(cid).isdigit() else None)
                if channel is not None:
                    lines.append(channel.mention)
                else:
                    lines.append("(deleted channel, id %s)" % cid)
            noxp_fields = [
                ("No XP" if i == 0 else "No XP (cont.)", chunk)
                for i, chunk in enumerate(_chunk_lines(lines))]
            sections.append(("No-XP channels (%d)" % len(no_xp), None,
                             noxp_fields))

        # Section 3: the channels that earn XP (counts, names when short).
        visible = list(getattr(guild, "text_channels", []) or [])
        giving = [c for c in visible if str(c.id) not in no_xp_set]
        rule = "Every text channel earns XP except the no-XP list above."
        if not xp_threads:
            rule += " Threads earn no XP right now (XP in threads is OFF)."
        joined = "\n".join(c.mention for c in giving)
        xp_fields = []
        if giving and len(joined) <= 1000:
            xp_fields.append(("Earn XP", joined))
        sections.append(("Channels that earn XP (%d of %d)"
                         % (len(giving), len(visible)), rule, xp_fields))

        embeds = _build_level_embeds(sections)
        view = LevelSettingsView(interaction.user.id, guild.id)
        # One embed per message (Discord caps total chars across all
        # embeds in one message at 6000); the Manage button rides on
        # the first message.
        first = True
        for em in embeds:
            if first:
                await interaction.respond(embed=em, view=view, ephemeral=True)
                first = False
            else:
                await interaction.followup.send(embed=em, ephemeral=True)

    @commands.slash_command(name="set_level_role", description="Set a role reward for reaching a level", guild_ids=GUILD_IDS)
    @extra_help("Members automatically receive the role when they reach the level. Rewards are cumulative. Members who already hold the level get the role right away (backfilled).")
    async def set_level_role(self, interaction, level: int, role: discord.Role):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "set_level_role", _default_admin_only):
            return
        if level < 2:
            return await interaction.respond("Level must be at least 2.", ephemeral=True)
        if role.is_default():
            return await interaction.respond(
                "@everyone can't be a level reward — pick a real role.", ephemeral=True)
        guild = interaction.guild
        gid = str(guild.id)
        db = await get_levels(gid)
        rewards = db.setdefault("settings", {}).setdefault("level_roles", {})
        rewards[str(level)] = str(role.id)
        await save_levels(gid, db)
        # P2-15: a reward configured after members already passed its
        # level used to never reach them, and a reward role above the
        # bot used to fail silently per member, so the admin thought
        # it was live when it never applied. Check the bot can manage
        # the role first; if not, say so plainly and skip the backfill
        # instead of failing once per member.
        me = guild.me
        can_manage = (me is not None
                      and getattr(me.guild_permissions, "manage_roles", False)
                      and me.top_role > role)
        if not can_manage:
            return await interaction.respond(
                f"✅ {role.mention} will be awarded at level **{level}**.\n"
                "⚠️ But the bot can't grant this role — it sits above the "
                "bot's highest role, or the bot lacks Manage Roles. Move "
                "the bot's role above it (Server Settings → Roles) and "
                "re-run this command to backfill members who already "
                "qualify.")
        # Backfill members who already hold the level. Deferred: the
        # grants are one Discord call each, so a big server takes a
        # while; capped per run (see BACKFILL_MAX).
        await interaction.defer()
        qualifying = [uid for uid, row in db.items()
                      if uid != "settings" and isinstance(row, dict)
                      and row.get("level", 1) >= level]
        added = already = skipped = 0
        failed = []
        for uid in qualifying[:BACKFILL_MAX]:
            member = guild.get_member(int(uid))
            if member is None:
                skipped += 1
                continue
            if role in member.roles:
                already += 1
                continue
            try:
                await member.add_roles(
                    role, reason="Level reward backfill: already level %d" % level)
                added += 1
            except discord.Forbidden:
                failed.append(member.display_name)
                print("[WARN] Backfill: could not grant %s to %s: Forbidden "
                      "(role above the bot or missing Manage Roles)."
                      % (role.name, member.display_name))
            except discord.HTTPException as exc:
                failed.append(member.display_name)
                print("[WARN] Backfill: could not grant %s to %s: %r"
                      % (role.name, member.display_name, exc))
        remaining = len(qualifying) - BACKFILL_MAX if len(qualifying) > BACKFILL_MAX else 0
        parts = [f"✅ {role.mention} will be awarded at level **{level}**."]
        bits = []
        if added:
            bits.append("%d member(s) backfilled" % added)
        if already:
            bits.append("%d already had it" % already)
        if skipped:
            bits.append("%d no longer in the server" % skipped)
        if failed:
            bits.append("could not grant to %d (%s)"
                        % (len(failed), ", ".join(failed[:5])))
        if bits:
            parts.append("Backfill: %s." % "; ".join(bits))
        if remaining:
            parts.append("%d more member(s) still qualify — run "
                         "/set_level_role again to continue the backfill."
                         % remaining)
        await interaction.followup.send("\n".join(parts))

    @commands.slash_command(name="remove_level_role", description="Remove a level role reward", guild_ids=GUILD_IDS)
    @extra_help("Stops awarding a role at the given level (members who already have it keep it).")
    async def remove_level_role(self, interaction, level: int):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "remove_level_role", _default_admin_only):
            return
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
    async def toggle_game_xp(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "toggle_game_xp", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        new_val = not settings.get("game_xp", GAME_XP_DEFAULT)
        settings["game_xp"] = new_val
        await save_levels(gid, db)
        state = "ON" if new_val else "OFF"
        detail = "voting now earns level XP" if new_val else "voting no longer earns level XP"
        await interaction.respond(f"🎮 Game XP is now **{state}** — {detail}.")

    @commands.slash_command(name="toggle_levels", description="Turn the level system on/off for this server", guild_ids=GUILD_IDS)
    @extra_help("Turns the whole level system on or off for this server. Off by default -- turn it on to start earning XP from messages, games, and voice.")
    async def toggle_levels(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "toggle_levels", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        new_val = not settings.get("levels_enabled", False)
        settings["levels_enabled"] = new_val
        await save_levels(gid, db)
        state = "ON" if new_val else "OFF"
        detail = ("members will now earn XP from messages, games, and voice"
                  if new_val else
                  "members will no longer earn XP, and level-ups stop")
        await interaction.respond(f"📊 Level system is now **{state}** — {detail}.")

    @commands.slash_command(name="toggle_thread_xp", description="Turn XP on/off for messages in threads", guild_ids=GUILD_IDS)
    @extra_help("Turns message XP on or off inside threads (ticket threads, discussion threads, forum posts). On by default -- turn it off so ticket threads don't earn XP.")
    async def toggle_thread_xp(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "toggle_thread_xp", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        settings = db.setdefault("settings", {})
        new_val = not settings.get("xp_in_threads", True)
        settings["xp_in_threads"] = new_val
        await save_levels(gid, db)
        state = "ON" if new_val else "OFF"
        detail = ("messages in threads now earn XP" if new_val
                  else "messages in threads no longer earn XP")
        await interaction.respond(f"🧵 XP in threads is now **{state}** — {detail}.",
                                  ephemeral=True)

    @commands.slash_command(name="toggle_level_messages", description="Turn your level-up messages on/off", guild_ids=GUILD_IDS)
    @extra_help("Turns your own level-up messages on or off. You still earn XP when they're off -- you just won't get the announcements.")
    async def toggle_level_messages(self, interaction):
        gid, uid = str(interaction.guild.id), str(interaction.user.id)
        db = await get_levels(gid)
        user = db.setdefault(uid, {"xp": 0, "level": 1,
                                   "username": interaction.user.display_name})
        new_val = not user.get("level_messages", True)
        user["level_messages"] = new_val
        await save_levels(gid, db)
        if new_val:
            await interaction.respond(
                "🔔 Level-up messages are now **ON** for you.", ephemeral=True)
        else:
            await interaction.respond(
                "🔕 Level-up messages are now **OFF** for you. You'll still earn XP, "
                "you just won't get the announcements.",
                ephemeral=True)

    @commands.slash_command(name="toggle_no_xp", description="Toggle XP gains in a channel", guild_ids=GUILD_IDS)
    @extra_help("Turns message XP on/off for a channel. Useful for bot-spam channels.")
    async def toggle_no_xp(self, interaction, channel: discord.TextChannel):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "toggle_no_xp", _default_admin_only):
            return
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

    @commands.slash_command(name="no_xp_bulk", description="Turn XP off/on in many channels at once", guild_ids=GUILD_IDS)
    @extra_help("Pick up to 25 channels at once, then disable XP in all of them (or turn XP back on). Useful for mod channels and bot-spam channels.")
    async def no_xp_bulk(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "no_xp_bulk", _default_admin_only):
            return
        gid = str(interaction.guild.id)
        db = await get_levels(gid)
        no_xp = db.get("settings", {}).get("no_xp_channels", [])
        if no_xp:
            current = ", ".join("<#%s>" % cid for cid in no_xp)
            current_text = "\n\nCurrently no-XP: %s" % current
        else:
            current_text = "\n\nNo channels are currently set to no-XP."
        view = NoXpBulkView(interaction.user.id, interaction.guild.id)
        await interaction.respond(
            content=("Pick channels below, then hit **Disable XP** to stop XP in all of them, "
                     "or **Enable XP** to turn XP back on in them." + current_text),
            view=view,
            ephemeral=True,
        )

    @commands.slash_command(name="xp_event", description="Start a bonus XP event", guild_ids=GUILD_IDS)
    @extra_help("Starts a server-wide XP multiplier event for the given minutes (multiplier 2-5).")
    async def xp_event(self, interaction, minutes: int,
                       multiplier: discord.Option(int, "XP multiplier (2-5)", default=2)):  # type: ignore
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "xp_event", _default_admin_only):
            return
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
    async def xp_event_end(self, interaction):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "xp_event_end", _default_admin_only):
            return
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
        if not await levels_enabled(interaction.guild.id):
            return await interaction.respond(
                "The level system is off in this server. An admin can turn it on with /toggle_levels.",
                ephemeral=True)
        target = interaction.user
        # P1-18 / P2-12: the daily claim is check-then-save with no lock --
        # two invocations in flight both pass the 20h check and both
        # collect. Hold the guild lock across the claim, then release it
        # before award_xp (which takes the lock itself).
        async with get_level_lock(gid):
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
        # Defer first: award_xp can take seconds when it levels the
        # member up (role rewards + level-up card + announcement), and
        # an interaction left unanswered for 3s expires (same 10062
        # as /add_xp, 2026-11-09).
        # The defer MUST be ephemeral: a public defer locks the whole
        # interaction's followups public, and Discord then ignores the
        # ephemeral flag on the level-up followup (live 2026-11-09:
        # the card was sent with ephemeral=True but stored flags=0).
        # Everything on this interaction -- the level-up card AND the
        # daily confirmation below -- renders ephemeral, visible only
        # to the person who claimed.
        await interaction.response.defer(ephemeral=True)
        gained = await award_xp(interaction.guild, target.id, target.display_name,
                                amount, fallback_channel=interaction.channel,
                                interaction=interaction)  # level-up goes ephemeral to the invoker
        msg = f"🎁 Daily claimed! **+{amount} XP** (🔥 {streak}-day streak)"
        if gained:
            # P2-11: report gained[-1]. The local `db` above was loaded
            # before award_xp ran, and award_xp reloads and saves its
            # own copy with the new level, so db[uid]["level"] is still
            # the PRE-award level -- the old line announced the level
            # the member had just left.
            msg += f"\n🎉 And that leveled you up to **{gained[-1]}**!"
        await interaction.followup.send(msg)

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
    async def set_levelup_message(self, interaction, message: str = None):
        from utils.permissions import check_slash_permission, _default_admin_only
        if not await check_slash_permission(interaction, "set_levelup_message", _default_admin_only):
            return
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
