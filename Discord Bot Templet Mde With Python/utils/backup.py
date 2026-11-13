"""Unified backup + restore for bot data.

Snapshots are one zip per run, stored under ``data/backups/``:

    <YYYYMMDD-HHMMSS>_<label>.zip

Each zip holds the live data files plus a ``manifest.json`` listing
every file with its size and SHA-256, so a snapshot can be verified
before anything is restored.

What is backed up:
  * The whole Postgres database (``bot.dump``) — every table in the
    database the bot is pointed at, bot tables and Logger tables
    alike, dumped with pg_dump (plain SQL, --clean --if-exists, so a
    restore drops the current tables and recreates the snapshot's).
    The dump runs through the ``havenly-postgres`` Docker container
    (``docker exec ... pg_dump``; inside the container the local
    socket uses trust auth, so no password is needed or passed).
    That requires Docker on the same host as the bot — the Nitro —
    so a snapshot taken on a machine without the container fails
    loudly instead of silently producing an empty backup.
  * The remaining JSON data files in ``data/``: mod_data, watchlist,
    and the eatyeet_* files.

Deliberately NOT backed up:
  * ``notification_read.json`` — per-user notification read-state. It
    is runtime state, not bot data, and restoring it would un-dismiss
    notifications. It is also on the never-touch list for this bot.
  * ``profiles.json.migrated`` — a one-time migration leftover.
  * Debug logs, ``.debug_enabled``, and the ``backups/`` dir itself.

Why no database table tracks snapshots: the registry lives in the
zip manifests on disk, so it survives exactly the disaster this
protects against — a lost or corrupted database. A table inside
the database would be gone when it is needed most.

Restore safety:
  1. A safety snapshot (label ``pre-restore``) of the CURRENT data is
     taken first, so a bad restore can itself be undone. The snapshot
     being restored is exempt from the retention prune that safety
     snapshot runs, so an old target outside retention cannot be
     deleted mid-restore (P2-26).
  2. The snapshot is extracted to a temp dir and every file is
     re-hashed against its manifest. A mismatch aborts the restore
     before any live data is touched.
  3. The Postgres dump is restored by piping it into psql inside
     the container (``docker exec -i ... psql -v ON_ERROR_STOP=1``),
     which drops the current tables and recreates the snapshot's.
     JSON files are written via a temp file + atomic replace. Every
     staged file is re-hashed against the manifest before any live
     data is touched, so a bad extract aborts with the live data
     still intact. A snapshot from the SQLite era (kind "sqlite")
     is refused outright — it cannot be restored into Postgres.
  4. If a file fails mid-restore, the files already applied are
     automatically rolled back from the safety snapshot (files the
     restore created that did not exist before it are removed), and
     the restore raises a RuntimeError naming exactly which files
     were applied, which file failed, and whether the rollback
     succeeded. A rollback that itself fails partway says so and
     names the files left un-rolled-back, so the operator can restore
     the named safety snapshot by hand (P2-27).
  4. After a restore, restart the bot: some cogs cache DB-backed
     settings in memory, and only a restart guarantees every cog
     re-reads the restored data.

Retention (applied on every new snapshot): the newest 14
``scheduled`` snapshots plus the newest 10 manual / pre-restore
snapshots are kept; older ones are deleted.
"""

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import threading
import zipfile
from datetime import datetime
from urllib.parse import urlparse

# utils/ sits at the bot root, so its parent is the bot folder.
BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BOT_ROOT, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

# The Postgres dump inside a snapshot zip. One dump covers the whole
# database (bot tables + Logger tables + json_* tables), which is why
# the old pair of SQLite files (bot.db, message_log.db) collapsed
# into this single entry.
PG_DUMP_NAME = "bot.dump"
PG_CONTAINER = "havenly-postgres"
PG_USER = "havenly_bot"

# JSON data files in data/. notification_read.json and
# profiles.json.migrated are excluded on purpose (see module docstring).
JSON_FILES = [
    "mod_data.json",
    "watchlist_data.json",
    "eatyeet_active.json",
    "eatyeet_rematch.json",
    "eatyeet_stats.json",
    "eatyeet_suggestions.json",
]

RETAIN_SCHEDULED = 14
RETAIN_OTHER = 10

# RLock: restore_snapshot() takes a safety snapshot first, so
# create_snapshot() must be re-entrant from inside a restore.
_lock = threading.RLock()


def scheduled_hour():
    """Hour of day (PC local time) for the daily scheduled snapshot."""
    try:
        hour = int(os.getenv("BACKUP_DAILY_HOUR", "4"))
    except ValueError:
        hour = 4
    return max(0, min(23, hour))


def _sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pg_database():
    """The database name the bot is pointed at, from DATABASE_URL.

    Resolved lazily (so importing this module never fails when the
    database is briefly unavailable). The backup dumps and restores
    whatever database the bot is using: ``havenly`` live, whatever
    staging database a test copy points at.
    """
    from data.DB.db import get_database_url

    url = urlparse(get_database_url())
    name = (url.path or "").lstrip("/")
    if not name:
        raise RuntimeError("DATABASE_URL has no database name: %r" % url)
    return name


def _pg_dump(db_name, dest_path, timeout=300):
    """Dump a Postgres database to a file with pg_dump.

    Runs inside the havenly-postgres container (``docker exec``), so
    the pg_dump binary and the server are always the same version.
    Inside the container the local socket uses trust auth, so no
    password is passed or read. Plain SQL format, --clean
    --if-exists (a restore drops the current tables first),
    --no-owner --no-privileges (portable: no ownership/ACLs, so the
    dump restores cleanly on a fresh container). A snapshot taken
    while the bot is running is still a consistent database --
    pg_dump takes one transaction snapshot.
    """
    if shutil.which("docker") is None:
        raise RuntimeError(
            "docker is not available on this host; the Postgres backup "
            "needs the havenly-postgres container (the Nitro)."
        )
    with open(dest_path, "wb") as fh:
        proc = subprocess.run(
            [
                "docker", "exec", PG_CONTAINER,
                "pg_dump", "-U", PG_USER, "-d", db_name,
                "--clean", "--if-exists",
                "--no-owner", "--no-privileges",
            ],
            stdout=fh, stderr=subprocess.PIPE, timeout=timeout,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            "pg_dump of %s failed (exit %d): %s"
            % (db_name, proc.returncode,
               proc.stderr.decode("utf-8", "replace")[:500])
        )


def _pg_restore(db_name, dump_path, timeout=300):
    """Restore a pg_dump file into a database by piping it to psql.

    Runs inside the havenly-postgres container (``docker exec -i``),
    so no password is passed or read. ON_ERROR_STOP=1 makes psql
    stop (and exit non-zero) at the first failing statement instead
    of ploughing on through a half-restored dump.
    """
    if shutil.which("docker") is None:
        raise RuntimeError(
            "docker is not available on this host; the Postgres restore "
            "needs the havenly-postgres container (the Nitro)."
        )
    with open(dump_path, "rb") as fh:
        proc = subprocess.run(
            [
                "docker", "exec", "-i", PG_CONTAINER,
                "psql", "-U", PG_USER, "-d", db_name,
                "-v", "ON_ERROR_STOP=1", "-q",
            ],
            stdin=fh, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, timeout=timeout,
        )
    if proc.returncode != 0:
        raise RuntimeError(
            "psql restore into %s failed (exit %d): %s"
            % (db_name, proc.returncode,
               proc.stderr.decode("utf-8", "replace")[:1000])
        )


def _safe_label(label):
    cleaned = "".join(
        ch if (ch.isalnum() or ch in "-_") else "_" for ch in (label or "")
    ).strip("_")
    return cleaned or "manual"


def _snapshot_path(name):
    """Resolve a snapshot name to a path inside BACKUP_DIR, or None
    when the name is not a plain snapshot filename (path traversal
    guard for web-supplied names)."""
    if not name or not isinstance(name, str):
        return None
    base = os.path.basename(name)
    if base != name or not base.endswith(".zip"):
        return None
    path = os.path.join(BACKUP_DIR, base)
    if os.path.dirname(os.path.abspath(path)) != os.path.abspath(BACKUP_DIR):
        return None
    return path


def _read_manifest(zip_path):
    """Manifest dict from a snapshot zip, or None if unreadable."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            with zf.open("manifest.json") as fh:
                data = json.load(fh)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _zip_entries_safe(zf):
    """Yield (name, ZipInfo) for entries that are plain top-level
    files — no absolute paths, no parent traversal, no directories."""
    for info in zf.infolist():
        name = info.filename
        if (
            not name
            or name.startswith("/")
            or ".." in name.split("/")
            or name.endswith("/")
            or "/" in name
        ):
            continue
        yield name, info


def create_snapshot(label="manual", exclude=None):
    """Take a snapshot of the live data. Returns a summary dict.

    Raises on failure; nothing is left half-written (the zip is built
    as a .tmp file and renamed into place only when complete).

    ``exclude`` is an optional set of snapshot filenames the retention
    prune must not delete (used by restore_snapshot so the snapshot
    being restored survives the prune this snapshot runs).
    """
    label = _safe_label(label)
    with _lock:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = "%s_%s.zip" % (stamp, label)
        final_path = os.path.join(BACKUP_DIR, name)
        # Same-second reruns (manual click + scheduler) must not
        # collide on the filename.
        counter = 1
        while os.path.exists(final_path):
            counter += 1
            name = "%s_%s-%d.zip" % (stamp, label, counter)
            final_path = os.path.join(BACKUP_DIR, name)

        manifest_files = []
        skipped = []
        with tempfile.TemporaryDirectory(prefix="backup-stage-") as stage:
            staged = {}
            try:
                tmp_dump = os.path.join(stage, PG_DUMP_NAME)
                _pg_dump(_pg_database(), tmp_dump)
                staged[PG_DUMP_NAME] = tmp_dump
            except Exception as exc:
                skipped.append(PG_DUMP_NAME)
                print("[Backup] Could not dump the database: %r" % (exc,))
                raise
            for json_name in JSON_FILES:
                live_path = os.path.join(DATA_DIR, json_name)
                if not os.path.exists(live_path):
                    skipped.append(json_name)
                    continue
                tmp_json = os.path.join(stage, json_name)
                shutil.copy2(live_path, tmp_json)
                staged[json_name] = tmp_json

            for zip_name, tmp_path in staged.items():
                manifest_files.append({
                    "name": zip_name,
                    "kind": "pg_dump" if zip_name == PG_DUMP_NAME else "json",
                    "size": os.path.getsize(tmp_path),
                    "sha256": _sha256_file(tmp_path),
                })

            manifest = {
                "version": 1,
                "label": label,
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "created_ts": datetime.now().timestamp(),
                "files": manifest_files,
                "skipped": skipped,
            }
            manifest_path = os.path.join(stage, "manifest.json")
            with open(manifest_path, "w", encoding="utf-8") as fh:
                json.dump(manifest, fh, indent=2)

            tmp_zip = final_path + ".tmp"
            try:
                with zipfile.ZipFile(
                    tmp_zip, "w", compression=zipfile.ZIP_DEFLATED
                ) as zf:
                    for zip_name, tmp_path in staged.items():
                        zf.write(tmp_path, arcname=zip_name)
                    zf.write(manifest_path, arcname="manifest.json")
                os.replace(tmp_zip, final_path)
            except Exception:
                # A failure mid-write (or a failed rename) used to
                # leave the half-written .tmp zip in data/backups/
                # forever -- _prune_locked only removes *.zip (P3-29).
                # Remove it so a failed snapshot leaves nothing
                # behind; the original error still propagates.
                try:
                    os.remove(tmp_zip)
                except OSError:
                    pass
                raise

        summary = {
            "name": name,
            "path": final_path,
            "label": label,
            "created_at": manifest["created_at"],
            "files": manifest_files,
            "skipped": skipped,
            "size": os.path.getsize(final_path),
        }
        _prune_locked(exclude=exclude)
        return summary


def _prune_locked(exclude=None):
    """Delete snapshots beyond retention. Caller must hold _lock.

    ``exclude`` is an optional set of filenames that are always kept,
    even when they fall outside retention.
    """
    try:
        entries = []
        for fname in os.listdir(BACKUP_DIR):
            if not fname.endswith(".zip"):
                continue
            path = os.path.join(BACKUP_DIR, fname)
            manifest = _read_manifest(path)
            if manifest:
                label = str(manifest.get("label") or "")
                ts = float(manifest.get("created_ts") or 0)
            else:
                label = ""
                ts = os.path.getmtime(path)
            entries.append((fname, path, label, ts))
    except FileNotFoundError:
        return
    scheduled = sorted(
        (e for e in entries if e[2] == "scheduled"),
        key=lambda e: e[3],
        reverse=True,
    )
    other = sorted(
        (e for e in entries if e[2] != "scheduled"),
        key=lambda e: e[3],
        reverse=True,
    )
    keep = {e[0] for e in scheduled[:RETAIN_SCHEDULED]}
    keep |= {e[0] for e in other[:RETAIN_OTHER]}
    if exclude:
        keep |= set(exclude)
    for fname, path, _label, _ts in entries:
        if fname not in keep:
            try:
                os.remove(path)
                print("[Backup] Pruned old snapshot: %s" % fname)
            except OSError as exc:
                print("[Backup] Could not prune %s: %r" % (fname, exc))


def list_snapshots():
    """Snapshots newest first. Each entry carries its manifest (or
    ok=False when the zip/manifest is unreadable)."""
    out = []
    try:
        names = [
            f for f in os.listdir(BACKUP_DIR) if f.endswith(".zip")
        ]
    except FileNotFoundError:
        return out
    for fname in names:
        path = os.path.join(BACKUP_DIR, fname)
        manifest = _read_manifest(path)
        if manifest:
            out.append({
                "name": fname,
                "label": str(manifest.get("label") or ""),
                "created_at": str(manifest.get("created_at") or ""),
                "created_ts": float(manifest.get("created_ts") or 0),
                "files": manifest.get("files") or [],
                "skipped": manifest.get("skipped") or [],
                "size": os.path.getsize(path),
                "ok": True,
            })
        else:
            out.append({
                "name": fname,
                "label": "",
                "created_at": "",
                "created_ts": os.path.getmtime(path),
                "files": [],
                "skipped": [],
                "size": os.path.getsize(path),
                "ok": False,
            })
    out.sort(key=lambda e: e["created_ts"], reverse=True)
    return out


def verify_snapshot(name):
    """Re-hash a snapshot's contents against its manifest.

    Returns (ok, problems): ok is False when the zip is unreadable,
    the manifest is missing, or any file fails its hash check.
    """
    path = _snapshot_path(name)
    if path is None or not os.path.exists(path):
        return False, ["Snapshot not found."]
    manifest = _read_manifest(path)
    if manifest is None:
        return False, ["Manifest is missing or unreadable."]
    expected = {
        f["name"]: f["sha256"]
        for f in (manifest.get("files") or [])
        if isinstance(f, dict) and "name" in f and "sha256" in f
    }
    problems = []
    try:
        with zipfile.ZipFile(path, "r") as zf:
            present = {n for n, _i in _zip_entries_safe(zf)}
            for zip_name, sha in expected.items():
                if zip_name not in present:
                    problems.append("Missing from zip: %s" % zip_name)
                    continue
                digest = hashlib.sha256()
                with zf.open(zip_name) as fh:
                    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != sha:
                    problems.append("Hash mismatch: %s" % zip_name)
    except zipfile.BadZipFile:
        return False, ["Snapshot zip is corrupt."]
    return (not problems), problems


class _ApplyError(Exception):
    """A snapshot apply failed partway through.

    Carries the per-file state so the caller can roll back and report
    exactly what was and was not applied. ``applied`` is the list of
    zip names already written to the live data, in order; ``failed``
    is the zip name of the file that raised ``error``.
    """

    def __init__(self, failed, error, applied, skipped):
        super().__init__(str(error))
        self.failed = failed
        self.error = error
        self.applied = list(applied)
        self.skipped = list(skipped)


def _apply_snapshot_files(zip_path, manifest, known):
    """Apply one snapshot zip's files to the live data.

    Extracts to a temp dir, pre-flights every staged file against the
    manifest (presence + SHA-256) BEFORE touching any live data, then
    applies the files in manifest order: the Postgres dump by piping
    it into psql inside the container, JSON files via temp file +
    atomic replace.

    ``known`` maps zip name -> (kind, target): ("pg", db_name) for
    the dump, ("file", live path) for a JSON file. A manifest entry
    whose kind is "sqlite" (a snapshot from the SQLite era) is
    refused outright -- it cannot be restored into Postgres.

    Returns (applied, skipped): applied is the zip names written to
    the live data, in order; skipped is the zip entries that are not
    live entries (unknown names). Manifest entries that are not live
    files are ignored, as before.

    Raises _ApplyError when a file fails to apply, after earlier
    files have already been written -- the caller must roll back.
    Raises RuntimeError (not _ApplyError) when the pre-flight fails,
    because no live data has been touched yet.
    """
    expected = {}
    for entry in manifest.get("files") or []:
        if isinstance(entry, dict) and entry.get("name") in known:
            expected[entry["name"]] = entry
    applied = []
    skipped = []
    with tempfile.TemporaryDirectory(prefix="restore-stage-") as stage:
        with zipfile.ZipFile(zip_path, "r") as zf:
            for zip_name, _info in _zip_entries_safe(zf):
                if zip_name == "manifest.json":
                    continue
                if zip_name not in known:
                    skipped.append(zip_name)
                    continue
                dest = os.path.join(stage, zip_name)
                with zf.open(zip_name) as src, open(dest, "wb") as out:
                    shutil.copyfileobj(src, out)
        # Pre-flight: every file the manifest says to restore must be
        # staged and hash-clean before any live data is touched. A
        # staged file that is missing or corrupt used to be silently
        # skipped mid-restore while the other files were applied and
        # the restore reported success; now it aborts up front.
        problems = []
        for zip_name, entry in expected.items():
            staged = os.path.join(stage, zip_name)
            if not os.path.exists(staged):
                problems.append("Missing from snapshot: %s" % zip_name)
                continue
            sha = entry.get("sha256")
            if sha and _sha256_file(staged) != sha:
                problems.append(
                    "Hash mismatch after extract: %s" % zip_name
                )
        if problems:
            raise RuntimeError(
                "Snapshot failed pre-flight: %s" % "; ".join(problems)
            )
        for zip_name, entry in expected.items():
            staged = os.path.join(stage, zip_name)
            kind, target = known[zip_name]
            try:
                if kind == "pg":
                    if entry.get("kind") != "pg_dump":
                        raise RuntimeError(
                            "Snapshot entry %s is a %s file, not a "
                            "Postgres dump; this snapshot is from the "
                            "SQLite era and cannot be restored into "
                            "Postgres." % (zip_name, entry.get("kind"))
                        )
                    _pg_restore(target, staged)
                else:
                    tmp_live = target + ".restore-tmp"
                    shutil.copy2(staged, tmp_live)
                    os.replace(tmp_live, target)
            except Exception as exc:  # noqa: BLE001
                raise _ApplyError(zip_name, exc, applied, skipped) from exc
            applied.append(zip_name)
    return applied, skipped


def _rollback_restore(name, apply_err, safety, known):
    """Roll a failed restore back to the safety snapshot, then raise.

    Only the files the failed restore actually applied need undoing;
    everything else is already at its pre-restore state. A file the
    restore applied that the safety snapshot does not have (the
    restore created it) is removed. Always raises RuntimeError
    describing the failed restore and the rollback outcome -- the
    caller never resumes a half-restored state.
    """
    safety_path = os.path.join(BACKUP_DIR, safety["name"])
    safety_manifest = _read_manifest(safety_path)
    rolled_back = []
    rollback_failed = []
    if safety_manifest is None:
        rollback_failed.append(
            "safety snapshot %s is unreadable -- no rollback attempted"
            % safety["name"]
        )
    else:
        safety_files = {
            entry.get("name"): entry
            for entry in (safety_manifest.get("files") or [])
            if isinstance(entry, dict) and entry.get("name") in known
        }
        to_restore = {
            zip_name: safety_files[zip_name]
            for zip_name in apply_err.applied
            if zip_name in safety_files
        }
        to_remove = [
            zip_name for zip_name in apply_err.applied
            if zip_name not in safety_files
        ]
        if to_restore:
            rollback_manifest = {
                "files": [
                    to_restore[zip_name]
                    for zip_name in apply_err.applied
                    if zip_name in to_restore
                ]
            }
            try:
                applied, _skipped = _apply_snapshot_files(
                    safety_path, rollback_manifest, known
                )
                rolled_back.extend(applied)
            except _ApplyError as rb_err:
                rolled_back.extend(rb_err.applied)
                rollback_failed.append(
                    "%s (%r)" % (rb_err.failed, rb_err.error)
                )
                for zip_name in apply_err.applied:
                    if zip_name in to_restore \
                            and zip_name not in rolled_back \
                            and zip_name != rb_err.failed:
                        rollback_failed.append(
                            "%s (rollback did not reach it)" % zip_name
                        )
            except RuntimeError as exc:
                rollback_failed.append(
                    "rollback pre-flight failed: %s" % (exc,)
                )
                for zip_name in apply_err.applied:
                    if zip_name in to_restore:
                        rollback_failed.append(
                            "%s (rollback did not reach it)" % zip_name
                        )
        for zip_name in to_remove:
            kind, target = known[zip_name]
            if kind == "pg":
                # A database is not a file: there is nothing to
                # remove, and a safety snapshot always carries the
                # dump, so this should never happen. Report it
                # rather than trying os.remove on a database name.
                rollback_failed.append(
                    "%s (safety snapshot has no dump to restore it "
                    "from; the database is left as the failed "
                    "restore left it)" % zip_name
                )
                continue
            try:
                os.remove(target)
            except FileNotFoundError:
                pass
            except OSError as exc:
                rollback_failed.append(
                    "%s (could not remove: %r)" % (zip_name, exc)
                )
                continue
            rolled_back.append("%s (removed)" % zip_name)

    if not apply_err.applied:
        outcome = "nothing had been applied, so no rollback was needed"
        state_note = "No live data had been changed yet."
    elif rolled_back and not rollback_failed:
        outcome = "rolled back from safety snapshot %s (%s)" % (
            safety["name"], ", ".join(rolled_back),
        )
        state_note = "Live data is back to its pre-restore state."
    elif rolled_back:
        outcome = (
            "PARTIAL rollback from safety snapshot %s: rolled back %s, "
            "but could not roll back %s"
            % (
                safety["name"],
                ", ".join(rolled_back),
                "; ".join(rollback_failed),
            )
        )
        state_note = (
            "Live data may be a mix of the snapshot and the previous "
            "state; restore safety snapshot %s to get back to the "
            "pre-restore state." % safety["name"]
        )
    else:
        outcome = "ROLLBACK FAILED from safety snapshot %s: %s" % (
            safety["name"],
            "; ".join(rollback_failed) or "no rollback attempted",
        )
        state_note = (
            "Live data may be a mix of the snapshot and the previous "
            "state; restore safety snapshot %s to get back to the "
            "pre-restore state." % safety["name"]
        )
    print(
        "[Backup] Restore of %s failed at %s (%r) after applying %s. %s."
        % (
            name,
            apply_err.failed,
            apply_err.error,
            ", ".join(apply_err.applied) if apply_err.applied else "nothing",
            outcome,
        )
    )
    raise RuntimeError(
        "Restore of %s failed at %s (%r) after applying %s. %s. %s"
        % (
            name,
            apply_err.failed,
            apply_err.error,
            ", ".join(apply_err.applied) if apply_err.applied else "nothing",
            outcome,
            state_note,
        )
    )


def restore_snapshot(name):
    """Restore a snapshot over the live data.

    Takes a pre-restore safety snapshot first, verifies the snapshot
    before touching anything live, then applies it. Returns a report
    dict with ``restored``, ``skipped``, ``safety_snapshot`` and (all
    empty on success) ``failed``, ``rolled_back``, ``rollback_failed``.
    Raises ValueError for a bad name and RuntimeError when the
    snapshot fails verification, fails its pre-flight, or fails
    mid-restore.

    A mid-restore failure is no longer a silent partial state: the
    files applied before the failure are automatically rolled back
    from the safety snapshot (files the restore created that did not
    exist before it are removed), and the raised RuntimeError names
    exactly which files were applied, which file failed, and whether
    the rollback succeeded. If the rollback itself fails partway, the
    error says so and names the files left un-rolled-back.
    """
    path = _snapshot_path(name)
    if path is None or not os.path.exists(path):
        raise ValueError("Snapshot not found: %s" % (name,))
    with _lock:
        ok, problems = verify_snapshot(name)
        if not ok:
            raise RuntimeError(
                "Snapshot failed verification: %s" % "; ".join(problems)
            )
        # Read the manifest now, while the target is known to exist,
        # and exempt the target from the prune the safety snapshot
        # runs below. Without the exemption, a target outside
        # retention was deleted by that prune and the manifest read
        # after it returned None, crashing the restore with an
        # AttributeError (P2-26).
        manifest = _read_manifest(path)
        if manifest is None:
            raise RuntimeError(
                "Snapshot manifest became unreadable: %s" % (name,)
            )
        safety = create_snapshot(
            "pre-restore", exclude={os.path.basename(path)}
        )
        if not os.path.exists(path):
            raise RuntimeError(
                "Snapshot %s disappeared during the safety snapshot; "
                "nothing was restored. Safety snapshot: %s"
                % (name, safety["name"])
            )

        # known maps zip name -> (kind, target): ("pg", db_name) for
        # the Postgres dump, ("file", live path) for a JSON file.
        known = {PG_DUMP_NAME: ("pg", _pg_database())}
        known.update(
            (json_name, ("file", os.path.join(DATA_DIR, json_name)))
            for json_name in JSON_FILES
        )
        try:
            restored, skipped = _apply_snapshot_files(
                path, manifest, known
            )
        except _ApplyError as apply_err:
            _rollback_restore(name, apply_err, safety, known)
        return {
            "restored": restored,
            "skipped": skipped,
            "safety_snapshot": safety["name"],
            "failed": [],
            "rolled_back": [],
            "rollback_failed": [],
        }


def delete_snapshot(name):
    """Delete one snapshot. Returns True when a file was removed."""
    path = _snapshot_path(name)
    if path is None or not os.path.exists(path):
        return False
    with _lock:
        os.remove(path)
    return True
