# Introduction

This handbook is the **how-it-works** companion to the README. The README
tells you how to *run* the bot; this tells you how the bot is *built* —
the architecture, the patterns each system uses, and copy-paste examples
for adding your own features.

If something here disagrees with the code, the code wins — update the
handbook when you change the architecture (there's a checklist for that
in [New-feature checklist](./checklist.md)).

## How to use this handbook

- **Fundamentals** — start here if you're new to the codebase: the
  project map, how the bot boots, how cogs work, permissions, and the
  helpers in `config.py`.
- **Data** — SQLite is the persistence layer (JSON files are legacy
  rollback copies since the October 2026 migration) and how to add tables.
- **Systems** — deep dives into the level system, Eat It or Yeet It, the
  Watch List, the Logger, and the October 2026 building-mode batch.
- **Guides** — copy-paste recipes, how testing works, and the checklist
  to run through for every new feature.

Every page has an **Edit this page** link at the bottom — if you spot
something outdated while working, fix it right there.
