# Eat It or Yeet It internals

Source: `cogs/fun_cog.py`.

## Round lifecycle

`/eatyeet` → `_make_round()` picks food + duration → posts the round
embed with vote buttons → a countdown task ticks the message (progress
bar, 🔨 **HAMMER TIME!** under 15 seconds) → expiry tallies votes, posts
results, awards game XP, and attaches the 🔁 rematch button.

> **Gotcha:** Discord renders `<t:...>` timestamps in embed
> *descriptions and fields* — but **not in footers**. A timestamp in a
> footer shows up as raw text like `<t:1791818966:R>`. The round's
> "Voting ends" line lives in the description for this reason.

## Restart safety

- Views use `timeout=None` and stable `custom_id`s, and are re-registered
  in `on_ready` (`_ensure_view()`) — see the
  [boot gotcha](./boot-sequence.md#gotcha-views-need-a-running-loop).
- Active rounds persist in the `eatyeet_active` table (SQLite); an expiry
  loop tallies anything that ended while the bot was down.
- Rematch settings persist per channel in the `eatyeet_rematch` table
  (SQLite), so 🔁 **Run it back** replays the same duration + food source
  even after a restart.

## Food sources

- **Auto** (default): 90% chance of a live meal from TheMealDB (free, no
  key) with the dish photo and a 🌐 *fresh* rarity; otherwise the local
  list. Session-level dedup of meal IDs.
- **Local only**: hand-written foods + community suggestions. No internet.
- **API only**: live meals only. If the API is unreachable, no round
  starts — explicit warning, never a silent fallback.

## Scoring

Majority voters earn points by rarity: common 1, weird / fresh /
community 2, cursed 3. Win streaks and best streaks are tracked per user,
and results name every voter on each side.

## Game data tables

`eatyeet_stats` (points, streaks), `eatyeet_suggestions` (community
pool), `eatyeet_active` (live rounds), `eatyeet_rematch` (per-channel
rematch settings) — all in SQLite since the October 2026 migration. The
old `data/eatyeet_*.json` files are kept as rollback copies.
