# Level system internals

Source: `cogs/Level_system.py`.

## Earning XP

`on_message` rolls `random.randint(xp_min, xp_max)` per message, subject
to the per-user cooldown and the `no_xp_channels` list.

## `award_xp()` — the single funnel

**All** XP flows through `award_xp()`: messages, `/add_xp`, `/daily`,
game votes, and voice time (banked in 5-minute chunks by the VoiceXP
cog). It:

1. Applies the active XP event multiplier — unless `apply_event=False`,
   which is how manual `/add_xp` grants stay exact.
2. Adds XP and loops `while xp >= level * 100`, rolling leftovers into
   the next level. (Level *n* costs *n* × 100 XP.)
3. Grants cumulative role rewards (`apply_level_rewards`).
4. Posts the level-up announcement (`announce_level_up`).

The core loop, simplified:

```python
async def award_xp(guild, user_id, display_name, amount,
                   fallback_channel=None, apply_event=True):
    db = await get_levels(str(guild.id))
    settings = db.setdefault("settings", {})

    # 1. XP event multiplier (2-5x while an event is active)
    if apply_event:
        until = settings.get("xp_event_until", 0)
        if until and time.time() < until:
            amount = int(amount * settings.get("xp_event_multiplier", 2))

    # 2. add XP, leveling up as many times as it takes
    user = db.setdefault(user_id, {"xp": 0, "level": 1,
                                   "username": display_name})
    user["xp"] += amount
    gained = []
    while user["xp"] >= user["level"] * 100:
        user["xp"] -= user["level"] * 100
        user["level"] += 1
        gained.append(user["level"])
    await save_levels(str(guild.id), db)

    # 3 + 4. rewards + announcement (only if they leveled up)
    if gained:
        await apply_level_rewards(guild, user_id, user["level"], settings)
        accent = _hex_to_rgb(user.get("card_color", "#5865F2"))
        await announce_level_up(guild, user_id, display_name, user["level"],
                                settings, fallback_channel, accent)
    return gained   # e.g. [6] — empty list if no level-up
```

Why one funnel? Every XP source gets level-ups, role rewards, event
multipliers, and announcements for free — and a bug fix in one place
fixes them all. If you add a new XP source, call `award_xp()`; don't
write your own math.

## Level-up announcements

Announcements go to the configured channel, or fall back to the channel
where the XP was earned. The text is the custom template if an admin set
one (`/set_levelup_message`, with `{user}` / `{name}` / `{level}`
placeholders) — otherwise the default message. A confetti card image is
attached when Pillow is installed; without Pillow it's text-only. Nothing
crashes either way.

## Cards

`build_rank_card()` and `build_levelup_card()` are pure functions: give
them avatar bytes and stats, get a PNG `BytesIO` back. Avatar download
failures fall back to a solid accent circle, so cards always render.
`/cardcolor` stores a per-user hex accent used by both cards; generation
runs in a thread (`asyncio.to_thread`) so it never blocks the event loop.

## Game XP hook

`fun_cog` calls the shared `award_level_xp()` after each Eat It or Yeet
It round: 10 XP per vote plus 10 × the game's majority points. It honors
the per-server `game_xp` toggle and XP events, and the results embed notes
when level XP was awarded.
