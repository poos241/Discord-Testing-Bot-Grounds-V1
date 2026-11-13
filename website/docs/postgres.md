# PostgreSQL

The bot stores everything in **PostgreSQL 17**, running in Docker.
This page covers the setup, the migration from SQLite, the
connect-race fix, backups, and how to query the database. The
two-bot side of the story is in [Two bots](./two-bots.md).

## The setup

One container, one database, localhost only:

```yaml
# servers/postgres/docker-compose.yml
services:
  postgres:
    image: postgres:17
    container_name: havenly-postgres
    restart: unless-stopped
    env_file:
      - .env.postgres
    ports:
      - "127.0.0.1:5432:5432"      # localhost only — nothing outside the machine can reach it
    volumes:
      - havenly_pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U havenly_bot -d havenly"]
      interval: 5s
      timeout: 5s
      retries: 12

volumes:
  havenly_pgdata:
```

- **Database:** `havenly` (production). `havenly_staging` is the
  staging database used for dry runs — never point the live bot at
  it.
- **Credentials:** `.env.postgres` holds the database password.
  It is strict `KEY=VALUE` — **no spaces around `=`** — because
  `docker compose` is pickier than the bot's `.env`. The file is
  mode 600 and lives only on the server. The bot's own `.env` is
  CRLF with spaces around `=`; the two files have different
  formats on purpose, so do not copy one over the other.
- **How the bot connects:** `DATABASE_URL` in the bot's `.env`:

  ```ini
  DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/havenly
  ```

  `data/DB/db.py` reads it from the bot-root `.env` and raises a
  clear error if it is missing. The code derives a sync URL
  (`postgresql+psycopg://`) and an async URL (plain
  `postgresql://` for `databases`/asyncpg) from it.

- **Drivers:** `asyncpg` 0.32.0 (async driver for `databases`)
  and `psycopg` 3.3.9 (sync driver for the JSON store and the
  Logger), installed as `psycopg[binary]`. Kept: `databases`
  0.9.0, SQLAlchemy 2.1.6. `asyncpg` and `psycopg` are installed
  on the live server but not yet listed in `requirements.txt`, so
  install them explicitly on a fresh setup
  (`pip install asyncpg "psycopg[binary]"`).

Check the container is healthy with:

```bash
docker exec havenly-postgres pg_isready -U havenly_bot -d havenly
docker logs havenly-postgres
```

## The migration from SQLite

On 2026-11-12 the data moved from SQLite (`bot.db`) to Postgres.
The route was **pgloader** (Docker `dimitri/pgloader:latest`),
loading into a schema created first by the patched code's own
`metadata.create_all()` plus the Logger and JSON-store schema
setup (46 tables).

Final cutover numbers (bot stopped, so final):

| Source | Rows moved | Verification |
| --- | --- | --- |
| `bot.db` (42 tables) | 4,969 | 0 count mismatches |
| `message_log.db` (5 tables) | 2,865 data rows | 0 count mismatches |

Verification covered per-table row counts on all 46 tables, 14
JSONB columns, and 7 spot checks (profiles, levels blob,
`command_permissions`, `qotd_questions`, `ghlog_items`, events,
messages) — all clean. Notable counts: profiles 2,519;
`introduction_status` 1,204; `command_permissions` 456;
`vrchat_accounts` 373; `qotd_questions` 296; events 1,132.

> **The old SQLite database is frozen, not live.** The live
> `bot.db` was frozen at 2026-11-12 11:41. Nothing writes to
> SQLite any more. The file is still in the repo folder as a
> legacy copy — do not delete it, and do not expect it to change.
> A rollback to SQLite would need the original (pre-Postgres)
> files restored, not just flipping the URL — the Postgres code
> uses `sqlalchemy.dialects.postgresql.insert` and cannot run on
> SQLite.

Postgres semantics worth knowing (verified during the build):

- Upserts are `INSERT ... ON CONFLICT DO UPDATE` (or
  `DO NOTHING`), keyed on the primary key. `ON CONFLICT DO
  UPDATE` checks NOT NULL on the *proposed* row even when a
  conflict exists — a partial-payload upsert that omits a NOT NULL
  column with no default fails. The only upsert table with a
  non-PK NOT NULL column is `vrchat_accounts` (`vrc_user_id`),
  and live callers always pass the full payload there.
- `command_permissions.allowed` is an `Integer` column (1 =
  allowed, 0 = denied), not a Boolean.
- `sqlalchemy.JSON` columns map to JSONB. The JSON store's
  `_rows_to_dict` accepts both a string and an already-parsed
  value, because Postgres JSONB returns real values — this fixed
  the SQLite NUMERIC-affinity quirk where a bare-number row was
  quarantined instead of loading.
- Level awards are serialised across processes with a Postgres
  advisory lock — `pg_advisory_xact_lock(hashtext("levels:<guild_id>")::bigint)`
  inside a transaction (`get_level_lock()` in
  `cogs/Level_system.py`). The old per-process `asyncio.Lock`
  silently lost XP when two processes awarded at once (the
  harness proved it: 44 XP instead of 80 on SQLite, 80 on
  Postgres). Never nest the lock.

## The connect race (and the fix)

The first cutover attempt (2026-11-12 11:42–11:52) was rolled
back because the bot's database layer broke under its own
concurrent startup. Login and command sync worked, but every
database operation failed forever after with errors like
`AssertionError('Connection is already acquired')` and
`InterfaceError('Pool.release() received invalid connection … is
not a member of this pool')`. The data move itself was correct
(0 mismatches) — the failure was in the connect path, not the
data.

**Root cause:** many cogs each call `await database.connect()` in
their `before_loop` hooks (QOTD, Lockdown, Timeout, and others),
and those hooks all fire at the same moment after `on_ready`.
On SQLite (aiosqlite) `connect()` is near-instant, so the
concurrent calls do not collide. On Postgres, `connect()` creates
the asyncpg pool (~1 s), so the concurrent calls raced inside the
`databases` library (0.9.0) and left the single shared connection
stuck in an "acquired" state.

**The fix** (three changes, in `data/DB/db.py`, `bot.py`,
`cogs/admin_cog.py`):

1. `SerialisedDatabase(Database)` — a subclass in `db.py` that
   holds a single `asyncio.Lock` around `connect()`: the
   check-and-connect is atomic, so exactly one caller creates the
   pool and the rest return as safe no-ops. Per-cog `connect()`
   calls are left in place but neutralised once connected.
2. A single explicit `await database.connect()` at the **top** of
   `on_ready` in `bot.py`, before the guild sanity check, the
   grant-rename migration, and the sync — in try/except that logs
   loudly but does not block startup.
3. A `connect()` in `admin_cog`'s `_before_board_refresh` — the
   board-refresh loop was the only loaded loop that touched the
   async DB without connecting first.

The harness was extended to simulate real startup (8 concurrent
connect callers plus a DB worker doing loop-first-iteration work)
and gated the retry: **99/99 checks passed** with the fix, and
the negative control (old code) failed with the exact live error.
The retry cutover (2026-11-12 ~12:11–12:21) succeeded, with 0 DB
errors and 12 active Postgres connections from the bot.

**Lesson for future work:** a harness that only exercises the
database layer can pass while the real startup still races. A
harness pass counts as evidence only when it replays the real
failure first and starts the bot the way the real bot starts,
including `on_ready` and the explicit connect.

## Backups

Snapshots are `pg_dump`-based. One dump file, `bot.dump`,
replaces the two old `.db` files; each snapshot is the dump plus
a manifest, zipped, with SHA-256 verification.

- **Who takes them:** the Helper. Its daily loop takes a snapshot
  at 04:00, and `/backup now` / `/backup status` (Helper-only
  commands) take and inspect manual snapshots. The dump runs
  through the container (`docker exec ... pg_dump --clean
  --if-exists --no-owner --no-privileges`); inside the container
  local socket auth is trust, so no password is passed on the
  command line.
- **Retention:** the newest 14 daily snapshots + the newest 10
  manual / pre-restore snapshots; older ones are pruned
  automatically. An old SQLite-era snapshot (kind `sqlite`) is
  refused outright on restore.
- **Nightly copy:** `nitro-backup.sh` runs at 2am and copies the
  server directories to `~/backups/` (14-day retention). That
  protects against deletes and bad edits — **not against the disk
  dying**, because everything is still on the same disk. The
  offsite step (an encrypted nightly upload of `bot.dump` to a
  private cloud folder) is recommended but not yet set up; until
  it is, the snapshots are a same-disk safety net, not an offsite
  backup.
- **Restore:** from a snapshot with `psql` through the container
  (see `utils/backup.py` for the exact invocation). A `pg_dump`
  restores with `pg_restore`/`psql` into a fresh Postgres — no
  SQLite files are involved. Test a restore into
  `havenly_staging` before relying on it.

## Querying the database

**From the server** — `psql` inside the container:

```bash
docker exec -it havenly-postgres psql -U havenly_bot -d havenly
```

Useful first checks:

```sql
SELECT count(*) FROM profiles;          -- 2,519 at cutover
SELECT count(*) FROM command_permissions;
SELECT * FROM pg_stat_activity WHERE usename = 'havenly_bot';
```

**From a PC** — Postgres only listens on `127.0.0.1:5432`, so a
remote tool cannot reach it directly. Use a GUI client that
supports an SSH tunnel (e.g. DBeaver): tunnel to the Nitro over
SSH, then connect to host `127.0.0.1`, port `5432`, database
`havenly`, user `havenly_bot` (password from `.env.postgres` on
the server — read it there, never paste it into chat or a shared
file).

**Staging:** `havenly_staging` holds a copy of the migrated data
for dry runs. Point a staging `.env` at it
(`DATABASE_URL=postgresql://<user>:<password>@127.0.0.1:5432/havenly_staging`)
and never point the live bot there. The staging harness creates
its own throwaway database (`havenly_harness`) and drops it when
it finishes, so harness runs never touch `havenly_staging` data.
