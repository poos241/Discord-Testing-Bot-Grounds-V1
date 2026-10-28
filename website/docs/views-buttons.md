# Views & buttons deep dive

Buttons (and other components) live inside `discord.ui.View` objects.
The game uses them for voting and rematch — here's how the pattern works
end to end.

## A persistent view

```python
class VoteView(discord.ui.View):
    def __init__(self, cog):
        # timeout=None: the view NEVER expires on its own.
        # Without this, buttons die after 3 minutes.
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Eat it",
        style=discord.ButtonStyle.green,
        custom_id="eatyeet:eat",   # stable ID — see below
    )
    async def eat_button(self, button, interaction):
        await self.cog.handle_vote(interaction, "eat")
```

Two things make a view **persistent** (surviving restarts):

1. `timeout=None` — otherwise Discord kills the view after 180s.
2. A stable `custom_id` — pycord uses it to route button presses back to
   this exact button after a restart.

## Re-registering on boot

Presses only reach your code if the view is registered with the bot. Since
cogs load before the event loop starts (and views need a loop), the game
creates views in `on_ready`, not in `__init__`:

```python
@commands.Cog.listener()
async def on_ready(self):
    self._ensure_view()   # builds VoteView + rematch view, bot.add_view(...)
```

The ticket system follows the same pattern: its panel/close/claim/reopen
views register once in `on_ready`, never in `__init__` (building a view
there crashed the whole bot with `no running event loop`).

> **Never** build a `View` at import time or in `__init__` — it raises
> `RuntimeError: no running event loop`. (There used to be a regression
> test for this, `test_noloop.py`, but no test files are currently in
> the repo — the rule still stands.)

## Routing with custom_id

One callback can serve many buttons by reading `custom_id`:

```python
@discord.ui.button(label="Run it back", custom_id="eatyeet:rematch")
async def rematch_button(self, button, interaction):
    # custom_id "eatyeet:rematch" tells us exactly which button this was,
    # even on a message sent before the last restart
    await self.start_rematch(interaction)
```

Convention: prefix with the system name (`"eatyeet:..."`) so IDs never
collide between cogs.

## The full lifecycle (voting)

1. `_make_round()` builds the food + duration and stores the round dict in
   the `eatyeet_active` table (SQLite) keyed by channel.
2. The round message is posted with `VoteView` attached.
3. A countdown task edits the message every 30s (every 5s in the last 30s).
4. On expiry: tally votes → results embed → award game XP → attach the
   rematch view → delete the round from the active store.
5. If the bot restarts mid-round: `on_ready` re-registers views, the
   expiry loop finds the overdue round in the SQLite store and tallies it.

## Gotchas

- **Editing a message with a view**: pass the *same* view instance (or a
  fresh equivalent) on every edit, or the buttons vanish.
- **Interaction timeout**: you have ~3 seconds to acknowledge a button
  press — `defer()` first if the handler does real work.
- **One press, one response**: every button callback must answer its
  interaction exactly once (`respond`, `defer`, or `edit_message`).
