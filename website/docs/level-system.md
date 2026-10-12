# Level system internals

Source: `cogs/Level_system.py`.

## Earning XP

`on_message` rolls `random.randint(xp_min, xp_max)` per message, subject
to the per-user cooldown and the `no_xp_channels` list.

## `award_xp()` — the single funnel

**All** XP flows through `award_xp()`: messages, `/add_xp`, `/daily`,
and game votes. It:

1. Applies the active XP event multiplier — unless `apply_event=False`,
   which is how manual `/add_xp` grants stay exact.
2. Adds XP and loops `while xp >= level * 100`, rolling leftovers into
   the next level. (Level *n* costs *n* × 100 XP.)
3. Grants cumulative role rewards (`apply_level_rewards`).
4. Posts the level-up announcement (`announce_level_up`).

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
