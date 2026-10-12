# Adding a food source

The game picks food through a small source pipeline in `fun_cog.py`. Here's
how the existing sources work and how to add one.

## How a round picks food

`_make_round()` asks the configured source for a `(food, rarity,
image_url)` triple:

- **Auto** (default): rolls a 90% chance → TheMealDB API for a live meal
  (🌐 *fresh* rarity + dish photo), otherwise the local list.
- **Local**: hand-written `FOODS` list + community suggestions from
  `eatyeet_suggestions.json`.
- **API only**: TheMealDB only. If the request fails, **no round starts**
  — an explicit warning instead of a silent fallback.

The API path uses a short timeout and session-level dedup of meal IDs so
the same dish doesn't repeat back-to-back.

## Source selection pattern

```python
async def _pick_food(self, source):
    if source == "api":
        meal = await self._fetch_meal()   # None on failure
        if meal is None:
            return None                  # caller warns, no round
        return meal["name"], "fresh", meal["photo"]
    if source == "auto" and random.random() < API_CHANCE:
        meal = await self._fetch_meal()
        if meal is not None:
            return meal["name"], "fresh", meal["photo"]
        # silent fallback to local — the game never breaks on network issues
    return self._pick_local_food()
```

Rules the pipeline follows:

1. **Never let a source crash a round.** API failures fall back (auto) or
   warn (api-only) — they never raise.
2. **Timeouts are short** (a few seconds). A hanging API must not hang
   the command.
3. **Dedup within a session** so repeats feel intentional, not broken.

## Adding your own source

1. Write an `async def _fetch_<thing>(self)` returning
   `(name, rarity, image_url)` or `None` on failure.
2. Add the source name to the `/eatyeet` source option and the rematch
   replay path (rematch reuses the same source).
3. Give it a rarity + point value in `RARITY_POINTS` / `RARITY_EMOJI` if
   it's a new rarity.
4. Add a mocked test in `test_api.py` — network is never hit in tests.

## Rarity & scoring

`RARITY_POINTS = {"common": 1, "weird": 2, "fresh": 2, "community": 2,
"cursed": 3}` — majority voters earn the round's point value. Keep new
rarities in the 1–3 range so one round can't dominate the leaderboard.
