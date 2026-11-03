"""Standalone website entry point (BRIDGE_CONTRACT.md section 7).

Run with:  python run_web.py
(or double-click run_web.bat, which runs the watchdog around this.)

The website runs as its own process with NO bot running: live Discord
data comes from the bot-side bridge, and every live endpoint degrades
to 503 while the bot is down instead of crashing or hanging.
"""

import os
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def main():
    from web.app import create_app
    from web.serve import run_server, get_host_port

    app = create_app(bot=None)

    host, port = get_host_port()
    # Standalone default host is 127.0.0.1 when WEB_HOST is unset, as
    # app.py's __main__ block already does.
    if os.environ.get("WEB_HOST") is None:
        host = "127.0.0.1"

    print(
        "[Web] Starting standalone website on %s:%s "
        "(separate process; no bot object in this process)" % (host, port)
    )
    run_server(app, host=host, port=port)


if __name__ == "__main__":
    main()
