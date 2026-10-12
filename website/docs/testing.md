# Testing

Headless tests live next to the code (`test_*.py`). They mock the storage
layer and Discord objects, so they run with **no token and no network**:

```bash
python test_levels.py    # level system
python test_levels2.py   # no-XP channels, XP events, daily, rank card
python test_levels3.py   # level-up card, card colors, custom messages
python test_gamexp.py    # Eat It or Yeet It -> level XP hook
python test_rematch.py   # rematch button
python test_noloop.py    # view-creation regression (see below)
```

## How the fakes work

Tests stub out `data.DB.Storage.storage` with in-memory dicts and use
small fake classes (`FakeMember`, `FakeChannel`, `FakeGuild`, `FakeCtx`)
in place of Discord objects. Network calls (avatar downloads, TheMealDB)
are patched with fakes returning canned bytes.

## The no-loop regression test

`test_noloop.py` imports every cog **without a running event loop** and
fails if any of them create a pycord `View` at import/`__init__` time.
If you add buttons or views, run this — views must be built in `on_ready`,
not at load time.

## Adding tests

When you add a feature, add a test file (or extend one) following the
existing fake-object pattern, and run the whole suite before pushing.
A good test asserts behavior ("daily streak increments"), not
implementation details.
