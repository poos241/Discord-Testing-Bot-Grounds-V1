# ============================================================
# Production WSGI server launcher
#
# Uses waitress (pure-Python, works on Windows) when available,
# falls back to Flask's dev server otherwise.
# ============================================================

import os


def run_server(app, host="0.0.0.0", port=5000):
    """Run the Flask app with waitress if installed, else Flask dev server."""
    try:
        from waitress import serve
        print(f"[Web] Starting with waitress on {host}:{port}")
        serve(app, host=host, port=port, threads=8)
    except ImportError:
        print("[Web] waitress not installed, using Flask dev server "
              "(pip install waitress for production use)")
        debug = os.environ.get("WEB_DEBUG", "").lower() in ("1", "true", "yes")
        app.run(host=host, port=port, debug=debug, use_reloader=False)


def get_host_port():
    """Read host/port from environment with sensible defaults."""
    host = os.environ.get("WEB_HOST", "0.0.0.0")
    try:
        port = int(os.environ.get("WEB_PORT", "5000"))
    except ValueError:
        port = 5000
    return host, port
