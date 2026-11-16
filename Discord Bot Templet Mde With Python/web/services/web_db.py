"""Connect the shared async database pool in the website process.

The website runs as a standalone process with no bot object, but its
storage layer (data.DB.Storage.storage) reads through the shared
``data.DB.db.database`` object on the website's local loop
(web/services/local_loop.py). That object is a pool that must be
connected once per process -- the bot connects it in on_ready, the
website never did, so every direct DB read failed with
"DatabaseBackend is not running" (leaderboard, directory, friends,
profiles, feed, notifications, modpanel, ...).

``ensure_connected`` is called once from create_app(); it is
idempotent (``SerialisedDatabase.connect`` short-circuits when already
connected) and never raises, so a DB outage only logs a warning and
the site still starts.
"""

import traceback


def ensure_connected(timeout=15):
    """Connect the shared database pool on the website's local loop.

    Returns True when connected (or already connected), False when the
    connect failed -- in which case DB-backed pages keep degrading to
    503 exactly as before, and the failure is logged loudly.
    """
    try:
        from data.DB.db import database
    except Exception:
        print("[Web] WARNING: could not import the database layer:")
        traceback.print_exc()
        return False

    try:
        if database.is_connected:
            return True
    except Exception:
        pass

    try:
        from web.services.local_loop import run_async

        run_async(database.connect(), timeout=timeout)
    except Exception:
        print("[Web] WARNING: could not connect to the database:")
        traceback.print_exc()
        return False

    print("[Web] Database connected (website process).")
    return True
