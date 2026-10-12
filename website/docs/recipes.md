# Common recipes

Copy-paste patterns used across the codebase.

## Per-user cooldown

A dict of timestamps, like `/level` uses:

```python
now = time.time()
if now - self.cooldowns.get(uid, 0) < 30:
    return await ctx.respond("Slow down!", ephemeral=True)
self.cooldowns[uid] = now
```

## A member who left

`guild.get_member()` returns `None` for departed members — fall back to a
stored username instead of crashing:

```python
member = ctx.guild.get_member(int(uid))
name = member.display_name if member else data.get("username", f"User ID {uid}")
```

## Safe int parsing

IDs are stored as strings; parse defensively:

```python
try:
    channel = guild.get_channel(int(channel_id))
except (ValueError, TypeError):
    channel = None
```

## Optional Pillow

Image features must degrade gracefully when Pillow isn't installed:

```python
try:
    from PIL import Image, ImageDraw, ImageFont
    _PIL_OK = True
except ImportError:
    _PIL_OK = False
```

…and branch to a text embed when `_PIL_OK` is `False`.

## Slow work off the event loop

CPU-bound work (like Pillow rendering) goes through `asyncio.to_thread`
so the bot stays responsive:

```python
card = await asyncio.to_thread(build_rank_card, avatar_bytes, name, level, xp, needed, rank)
```
