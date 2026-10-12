# Eat It or Yeet It internals

Source: `cogs/fun_cog.py`.

## Round lifecycle

`/eatyeet` → `_make_round()` picks food + duration → posts the round
embed with vote buttons → a countdown task ticks the message (progress
bar, 🔨 **HAMMER TIME!** under 15 seconds) → expiry tallies votes, posts
results, awards game XP, and attaches the 🔁 rematch button.

## Restart safety

- Views use `timeout=None` and stable `custom_id`s, and are re-registered
  in `on_ready` (`_ensure_view()`) — see the
  [boot gotcha](./boot-sequence.md#gotcha-views-need-a-running-loop).
- Active rounds persist in `eatyeet_active.json`; an expiry loop tallies
  anything that ended while the bot was down.
- Rematch settings persist per channel in `eatyeet_rematch.json`, so
  🔁 **Run it back** replays the same duration + food source even after a
  restart.

## Food sources

- **Auto** (default): 45% chance of a live meal from TheMealDB (free, no
  key) with the dish photo and a 🌐 *fresh* rarity; otherwise the local
  list. Session-level dedup of meal IDs.
- **Local only**: hand-written foods + community suggestions. No internet.
- **API only**: live meals only. If the API is unreachable, no round
  starts — explicit warning, never a silent fallback.

## Scoring

Majority voters earn points by rarity: common 1, weird / fresh /
community 2, cursed 3. Win streaks and best streaks are tracked per user,
and results name every voter on each side.

## Game data files

`data/eatyeet_stats.json` (points, streaks), `data/eatyeet_suggestions.json`
(community pool), `data/eatyeet_active.json` (live rounds),
`data/eatyeet_rematch.json` (per-channel rematch settings).
