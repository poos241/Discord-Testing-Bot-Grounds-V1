"""Watchdog: keep one process alive (BRIDGE_CONTRACT.md section 7).

Usage:
    python watchdog.py bot    -- run bot.py, relaunch on crash/restart
    python watchdog.py web    -- run run_web.py, relaunch on crash/restart

Restart rules:
  - exit code 1 (crash) or 42 (explicit restart request) -> relaunch.
  - exit code 0 (clean shutdown) -> stop, do not relaunch.
  - any other exit code -> loud [ERROR], stop, do not relaunch.
  - burst guard: more than 5 restarts in 60 s -> loud [ERROR], stop.
  - Ctrl+C (KeyboardInterrupt) -> stop the child and exit cleanly
    without restarting, so Ctrl+C still stops everything.

The bot watchdog and the website watchdog are independent: a website
crash never restarts the bot and vice versa. Startup order does not
matter -- each side degrades cleanly while the other is down.
"""

import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

COMMANDS = {
    "bot": [sys.executable, str(ROOT_DIR / "bot.py")],
    "web": [sys.executable, str(ROOT_DIR / "run_web.py")],
}

RESTART_CODES = (1, 42)
MAX_RESTARTS = 5
BURST_WINDOW_S = 60


def _creationflags():
    # On Windows, put the child in its own process group so a console
    # Ctrl+C reaches only the watchdog, not the child: the watchdog
    # then stops the child itself and exits cleanly instead of the
    # child dying with code 1 and being relaunched.
    if sys.platform == "win32":
        return subprocess.CREATE_NEW_PROCESS_GROUP
    return 0


def main(argv):
    if len(argv) != 2 or argv[1] not in COMMANDS:
        print("Usage: python watchdog.py bot|web")
        return 2

    name = argv[1]
    command = COMMANDS[name]
    restarts = []  # monotonic timestamps of relaunches

    while True:
        print("[WATCHDOG] Starting %s: %s" % (name, " ".join(command)), flush=True)
        try:
            proc = subprocess.Popen(
                command, cwd=str(ROOT_DIR),
                creationflags=_creationflags(),
            )
        except Exception as exc:
            print("[ERROR] Watchdog could not start %s: %r" % (name, exc), flush=True)
            return 1
        try:
            code = proc.wait()
        except KeyboardInterrupt:
            print("[WATCHDOG] KeyboardInterrupt: stopping %s (no restart)" % name, flush=True)
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
            return 0
        print("[WATCHDOG] %s exited with code %s" % (name, code), flush=True)
        if code == 0:
            print("[WATCHDOG] %s stopped cleanly; watchdog exiting." % name, flush=True)
            return 0
        if code not in RESTART_CODES:
            print("[ERROR] %s exited with unexpected code %s; not restarting." % (name, code), flush=True)
            return code
        now = time.monotonic()
        restarts.append(now)
        restarts = [t for t in restarts if now - t <= BURST_WINDOW_S]
        if len(restarts) > MAX_RESTARTS:
            print("[ERROR] %s restarted more than %d times in %ds; "
                  "burst guard tripped, giving up." % (name, MAX_RESTARTS, BURST_WINDOW_S), flush=True)
            return 1
        print("[WATCHDOG] Restarting %s (restart %d in the last %ds)..."
              % (name, len(restarts), BURST_WINDOW_S), flush=True)


if __name__ == "__main__":
    sys.exit(main(sys.argv))
