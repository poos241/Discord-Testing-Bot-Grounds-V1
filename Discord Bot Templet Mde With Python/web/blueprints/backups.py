"""Backups page: scheduled snapshots + mod-only restore from the web UI.

Snapshots live in ``data/backups/`` as one zip each (see
``utils/backup.py``). This blueprint only lists them, takes manual
ones, deletes them, serves downloads, and restores them — all behind
the moderator gate below.

Gating: backups are bot-wide, not per-server, so there is no guild id
in the URL to gate on. Instead every route requires a login AND the
moderator tier on at least one guild the user shares with the bot
(the same "moderator" tier the nav uses for the Staff Handbook link).
A plain member or a logged-out visitor gets the 403 page.

Restore flow (see utils/backup.py for the details): the restore first
takes a ``pre-restore`` safety snapshot of the CURRENT data and
verifies the chosen snapshot's hashes before touching anything live,
so a bad restore can itself be undone. After restoring, the bot must
be restarted — some cogs cache DB-backed settings in memory — and the
page says so on every restore.
"""

import secrets
from urllib.parse import quote

from flask import (
    Blueprint,
    abort,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from utils.backup import (
    BACKUP_DIR,
    create_snapshot,
    delete_snapshot,
    list_snapshots,
    restore_snapshot,
    scheduled_hour,
)
from web.blueprints.auth import get_csrf_token, get_user_guilds
from web.security.decorators import require_login
from web.services.permissions import has_access

backups_api = Blueprint("backups", __name__)


def _is_moderator():
    """Logged-in user holds the moderator tier on any shared guild."""
    if not session.get("user"):
        return False
    try:
        guilds = get_user_guilds() or []
    except Exception:
        return False
    for guild in guilds:
        gid = guild.get("id") if isinstance(guild, dict) else None
        if gid and has_access(gid, "moderator"):
            return True
    return False


def _require_mod():
    if not session.get("user"):
        abort(401)
    if not _is_moderator():
        abort(403)


def _check_csrf():
    """Accept the header token (JSON callers) or the form field
    (plain form posts on this page). Returns an error string, else
    None."""
    supplied = (
        request.headers.get("X-CSRF-Token")
        or request.headers.get("X-CSRFToken")
        or request.form.get("csrf_token")
        or ""
    ).strip()
    expected = get_csrf_token()
    if not supplied or not secrets.compare_digest(supplied, expected):
        return "Invalid CSRF token."
    return None


def _go(notice=None, error=None):
    target = url_for("backups.page")
    if error:
        return redirect(target + "?error=" + quote(error))
    if notice:
        return redirect(target + "?notice=" + quote(notice))
    return redirect(target)


@backups_api.get("/backups")
@require_login
def page():
    _require_mod()
    return render_template(
        "backups.html",
        snapshots=list_snapshots(),
        scheduled_hour=scheduled_hour(),
        notice=request.args.get("notice", ""),
        error=request.args.get("error", ""),
    )


@backups_api.post("/backups/create")
@require_login
def create():
    _require_mod()
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(error=csrf_error)
    try:
        summary = create_snapshot("manual")
    except Exception as exc:
        print("[Backups] Manual snapshot failed: %r" % (exc,))
        return _go(error="Snapshot failed: %r" % (exc,))
    return _go(
        notice="Snapshot saved: %s (%d files)."
        % (summary["name"], len(summary["files"]))
    )


@backups_api.post("/backups/restore")
@require_login
def restore():
    _require_mod()
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(error=csrf_error)
    name = (request.form.get("name") or "").strip()
    if not name:
        return _go(error="No snapshot selected.")
    try:
        report = restore_snapshot(name)
    except ValueError:
        return _go(error="Snapshot not found.")
    except RuntimeError as exc:
        return _go(error=str(exc))
    except Exception as exc:
        print("[Backups] Restore failed: %r" % (exc,))
        return _go(error="Restore failed: %r" % (exc,))
    return _go(
        notice="Restored %s (%d files). Safety snapshot %s was taken "
        "first, so this can be undone. Restart the bot so every cog "
        "picks up the restored data."
        % (
            name,
            len(report["restored"]),
            report["safety_snapshot"],
        )
    )


@backups_api.post("/backups/delete")
@require_login
def delete():
    _require_mod()
    csrf_error = _check_csrf()
    if csrf_error:
        return _go(error=csrf_error)
    name = (request.form.get("name") or "").strip()
    if not name:
        return _go(error="No snapshot selected.")
    if delete_snapshot(name):
        return _go(notice="Deleted snapshot %s." % name)
    return _go(error="Snapshot not found.")


@backups_api.get("/backups/download/<name>")
@require_login
def download(name):
    _require_mod()
    # Reuse the traversal guard from utils/backup.py by resolving
    # through the same rules list_snapshots() already enforces:
    # only a name this page listed may be downloaded.
    known = {s["name"] for s in list_snapshots()}
    if name not in known:
        abort(404)
    import os

    path = os.path.join(BACKUP_DIR, name)
    return send_file(
        path,
        as_attachment=True,
        download_name=name,
        mimetype="application/zip",
    )
