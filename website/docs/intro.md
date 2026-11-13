# Introduction

This handbook is the **how-it-works** companion to the README. The README
tells you how to *run* the bot; this tells you how the bot is *built* —
the architecture, the patterns each system uses, and copy-paste examples
for adding your own features.

If something here disagrees with the code, the code wins — update the
handbook when you change the architecture (there's a checklist for that
in [New-feature checklist](./checklist.md)).

## Two bots, one database

The system is **two bots sharing one codebase and one database**:

- **Havenly Bot 2.0** (the main bot) — the face of the system:
  real-time moderation, levels, games, QOTD, help. 54 top-level /
  83 runnable commands.
- **Havenly Helper** (the worker bot) — the back office: setup and
  config, batch jobs (scans, backfills, backups), and the timeout
  board. 11 top-level / 30 runnable commands, zero shared with the
  main bot.

They share one **PostgreSQL 17** database (in Docker) and talk to
each other through a small local **bridge hub**. The split is
*setup vs. use*: a command that does something right now lives on
the main bot; a command that sets something up or runs a batch job
lives on the Helper. Start with [Two bots](./two-bots.md) and
[PostgreSQL](./postgres.md) — those two pages are the architecture
everything else hangs off.

## How to use this handbook

- **Fundamentals** — start here if you're new to the codebase: the
  project map, how the bot boots, how cogs work, how commands are
  built and split across the two bots, permissions, and the helpers
  in `config.py`.
- **Data** — [PostgreSQL](./postgres.md) is the persistence layer.
  The old SQLite `bot.db` is frozen (2026-11-12) — nothing writes
  to it any more. This section covers the data layer and how to add
  tables.
- **Systems** — deep dives into the level system, Eat It or Yeet It,
  the Watch List, the Logger, and the October 2026 building-mode
  batch. Each system's commands are split across the two bots — see
  [Commands](./commands.md) and the README's Systems section for
  which bot runs what.
- **Guides** — copy-paste recipes, how testing works, and the
  checklist to run through for every new feature.

Every page has an **Edit this page** link at the bottom — if you spot
something outdated while working, fix it right there.
