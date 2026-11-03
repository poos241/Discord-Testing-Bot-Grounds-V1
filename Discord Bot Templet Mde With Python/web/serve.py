# ============================================================
# Production WSGI server launcher
#
# Uses waitress (pure-Python, works on Windows) when available,
# falls back to Flask's dev server otherwise.
# ============================================================

import os


def run_server(app, host="0.0.0.0", port=5000):
    """Run the Flask app with waitress if installed, else Flask dev server.

    A bind failure is reported loudly ([ERROR]) and re-raised so the
    process exits non-zero (the watchdog restarts it) instead of dying
    silently on a taken port.
    """
    try:
        from waitress import serve
        print(f"[Web] Starting with waitress on {host}:{port}")
        try:
            serve(app, host=host, port=port, threads=8)
        except OSError as exc:
            print(f"[ERROR] Web server failed to bind {host}:{port}: {exc!r}")
            raise
        print(f"[Web] Server stopped on {host}:{port}")
    except ImportError:
        print("[Web] waitress not installed, using Flask dev server "
              "(pip install waitress for production use)")
        debug = os.environ.get("WEB_DEBUG", "").lower() in ("1", "true", "yes")
        try:
            app.run(host=host, port=port, debug=debug, use_reloader=False)
        except OSError as exc:
            print(f"[ERROR] Web server failed to bind {host}:{port}: {exc!r}")
            raise
        print(f"[Web] Server stopped on {host}:{port}")


def get_host_port():
    """Read host/port from environment with sensible defaults."""
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("WEB_PORT", "5000"))
    except ValueError:
        port = 5000
    return host, port
