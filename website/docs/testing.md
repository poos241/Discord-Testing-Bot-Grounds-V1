# Testing

Headless tests live next to the code (`test_*.py`). They mock the storage
layer and Discord objects, so they run with **no token and no network**.
The established suite covered the level system (`test_levels.py`,
`test_levels2.py` for no-XP channels, XP events, daily, rank card,
`test_levels3.py` for level-up card, card colors, custom messages),
the Eat It or Yeet It → level XP hook (`test_gamexp.py`), the rematch
button (`test_rematch.py`), the API food source (`test_api.py`), and the
view-creation regression (`test_noloop.py`, see below).

> **Current state:** no `test_*.py` files are in the repo right now, so
> there is no suite to run until they are restored. The patterns below
> are still the way tests were written — follow them when adding tests
> back.

## How the fakes work

Tests stub out `data.DB.Storage.storage` with in-memory dicts and use
small fake classes (`FakeMember`, `FakeChannel`, `FakeGuild`, `FakeCtx`)
in place of Discord objects. Network calls (avatar downloads, TheMealDB)
are patched with fakes returning canned bytes.

## The no-loop regression test

`test_noloop.py` imported every cog **without a running event loop** and
failed if any of them created a pycord `View` at import/`__init__` time.
Views must be built in `on_ready`, not at load time — that rule stands
whether or not the test file is currently in the repo.

## Adding tests

When you add a feature, add a test file (or extend one) following the
existing fake-object pattern, and run the whole suite before pushing —
once test files are back in the repo. A good test asserts behavior
("daily streak increments"), not implementation details.
