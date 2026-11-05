# Level system internals

Source: `cogs/Level_system.py`.

## Earning XP

`on_message` rolls `random.randint(xp_min, xp_max)` per message, subject
to the per-user cooldown and the `no_xp_channels` list. **The level
system is off by default** (`settings["levels_enabled"]`, default
`False`): `on_message` returns early and `award_xp()` returns `[]`
immediately while off, so nothing earns XP from any source until an
admin runs `/toggle_levels`. `/daily`, `/add_xp`, and the panel add-XP
button refuse while off.

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

Announcements go to the configured channel. If no level-up channel is
set, the announcement is sent to the user by DM instead of the public
channel where they leveled up — closed DMs fail silently with no
public fallback. The text is the custom template if an admin set one
(`/set_levelup_message`, with `{user}` / `{name}` / `{level}`
placeholders) — otherwise the default message. A confetti card image is
attached when Pillow is installed; without Pillow it's text-only. Nothing
crashes either way.

**Per-user opt-out.** `user_data["level_messages"]` (default `True`)
controls whether that user gets announcements at all. `/toggle_level_messages`
flips it (open to everyone, ephemeral reply); opted-out users still earn
XP and role rewards, only the announcement is skipped. Every level-up
message names `/toggle_level_messages` so users can opt out.

## No-XP channels

`settings["no_xp_channels"]` is a list of channel ID strings.
`on_message` skips any channel in it. `/toggle_no_xp` flips one channel;
`/no_xp_bulk` opens a picker (up to 25 text channels at once) with
**Disable XP** / **Enable XP** buttons that add or remove all picked
channels in one batch. Only the admin who opened the picker can use it.

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
