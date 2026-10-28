"""Unified backup + restore for bot data.

Snapshots are one zip per run, stored under ``data/backups/``:

    <YYYYMMDD-HHMMSS>_<label>.zip

Each zip holds the live data files plus a ``manifest.json`` listing
every file with its size and SHA-256, so a snapshot can be verified
before anything is restored.

What is backed up:
  * ``bot.db`` (bot root) and ``data/message_log.db`` — copied with the
    SQLite backup API, never a raw file copy, so a snapshot taken while
    the bot is running is still a consistent database.
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
protects against — a lost or corrupted ``bot.db``. A table inside
``bot.db`` would be gone when it is needed most.

Restore safety:
  1. A safety snapshot (label ``pre-restore``) of the CURRENT data is
     taken first, so a bad restore can itself be undone.
  2. The snapshot is extracted to a temp dir and every file is
     re-hashed against its manifest. A mismatch aborts the restore
     before any live file is touched.
  3. SQLite files are restored through the SQLite backup API into the
     live file (the running bot keeps its own handles; the file is
     never replaced out from under it). JSON files are written via a
     temp file + atomic replace.
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
import sqlite3
import tempfile
import threading
import zipfile
from datetime import datetime

# utils/ sits at the bot root, so its parent is the bot folder.
BOT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BOT_ROOT, "data")
BACKUP_DIR = os.path.join(DATA_DIR, "backups")

BOT_DB_PATH = os.path.join(BOT_ROOT, "bot.db")
MESSAGE_LOG_DB_PATH = os.path.join(DATA_DIR, "message_log.db")

# (name inside the zip, live path on disk)
DB_FILES = [
    ("bot.db", BOT_DB_PATH),
    ("message_log.db", MESSAGE_LOG_DB_PATH),
]

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


def _sqlite_copy(source_path, dest_path, timeout=30):
    """Copy a SQLite database with the backup API (consistent even
    while the bot is running and the database is in use)."""
    src = sqlite3.connect(source_path, timeout=timeout)
    try:
        dst = sqlite3.connect(dest_path, timeout=timeout)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


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


def create_snapshot(label="manual"):
    """Take a snapshot of the live data. Returns a summary dict.

    Raises on failure; nothing is left half-written (the zip is built
    as a .tmp file and renamed into place only when complete).
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
            for zip_name, live_path in DB_FILES:
                if not os.path.exists(live_path):
                    skipped.append(zip_name)
                    continue
                tmp_db = os.path.join(stage, zip_name)
                _sqlite_copy(live_path, tmp_db)
                staged[zip_name] = tmp_db
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
                    "kind": "sqlite" if zip_name.endswith(".db") else "json",
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
            with zipfile.ZipFile(
                tmp_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as zf:
                for zip_name, tmp_path in staged.items():
                    zf.write(tmp_path, arcname=zip_name)
                zf.write(manifest_path, arcname="manifest.json")
            os.replace(tmp_zip, final_path)

        summary = {
            "name": name,
            "path": final_path,
            "label": label,
            "created_at": manifest["created_at"],
            "files": manifest_files,
            "skipped": skipped,
            "size": os.path.getsize(final_path),
        }
        _prune_locked()
        return summary


def _prune_locked():
    """Delete snapshots beyond retention. Caller must hold _lock."""
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


def restore_snapshot(name):
    """Restore a snapshot over the live data.

    Takes a pre-restore safety snapshot first, verifies the snapshot
    before touching anything live, then applies it. Returns a report
    dict. Raises ValueError for a bad name and RuntimeError when the
    snapshot fails verification.
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
        safety = create_snapshot("pre-restore")

        manifest = _read_manifest(path)
        known = dict(DB_FILES)
        known.update(
            (json_name, os.path.join(DATA_DIR, json_name))
            for json_name in JSON_FILES
        )
        restored = []
        skipped = []
        with tempfile.TemporaryDirectory(prefix="restore-stage-") as stage:
            with zipfile.ZipFile(path, "r") as zf:
                for zip_name, _info in _zip_entries_safe(zf):
                    if zip_name == "manifest.json":
                        continue
                    if zip_name not in known:
                        skipped.append(zip_name)
                        continue
                    dest = os.path.join(stage, zip_name)
                    with zf.open(zip_name) as src, open(dest, "wb") as out:
                        shutil.copyfileobj(src, out)
            for entry in manifest.get("files") or []:
                zip_name = entry.get("name")
                if zip_name not in known:
                    continue
                staged = os.path.join(stage, zip_name)
                if not os.path.exists(staged):
                    skipped.append(zip_name)
                    continue
                live_path = known[zip_name]
                if entry.get("kind") == "sqlite":
                    _sqlite_copy(staged, live_path)
                else:
                    tmp_live = live_path + ".restore-tmp"
                    shutil.copy2(staged, tmp_live)
                    os.replace(tmp_live, live_path)
                restored.append(zip_name)
        return {
            "restored": restored,
            "skipped": skipped,
            "safety_snapshot": safety["name"],
        }


def delete_snapshot(name):
    """Delete one snapshot. Returns True when a file was removed."""
    path = _snapshot_path(name)
    if path is None or not os.path.exists(path):
        return False
    with _lock:
        os.remove(path)
    return True
