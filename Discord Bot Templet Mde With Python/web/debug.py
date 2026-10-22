# ============================================================
# Debug system — master toggle for bot + web debugging
#
# Priority (highest wins):
#   1. Runtime flag file (toggled via /debug command or web UI)
#   2. DEBUG env var ("1", "true", "yes")
#
# Toggle at runtime without restarting:
#   - Discord: /debug on | /debug off | /debug status (admin only)
#   - Web: POST /api/debug/toggle  (requires login)
# ============================================================

import os
import time
from pathlib import Path

_FLAG_FILE = Path(__file__).resolve().parent.parent / "data" / ".debug_enabled"

_TRUE_VALUES = {"1", "true", "yes", "on"}


def _env_enabled():
    return os.environ.get("DEBUG", "").lower() in _TRUE_VALUES


def _flag_enabled():
    try:
        if _FLAG_FILE.exists():
            return _FLAG_FILE.read_text().strip().lower() in _TRUE_VALUES
    except Exception:
        pass
    return None  # no flag file = no opinion


def is_enabled():
    """True if debugging is on (flag file wins, else env var)."""
    flag = _flag_enabled()
    if flag is not None:
        return flag
    return _env_enabled()


def set_enabled(on: bool):
    """Set the runtime flag (persists across restarts until changed)."""
    try:
        _FLAG_FILE.parent.mkdir(parents=True, exist_ok=True)
        _FLAG_FILE.write_text("1" if on else "0")
        return True
    except Exception:
        return False


def clear_flag():
    """Remove the runtime flag so the env var decides again."""
    try:
        if _FLAG_FILE.exists():
            _FLAG_FILE.unlink()
        return True
    except Exception:
        return False


def log(category: str, message: str):
    """Timestamped debug log. Only prints when debugging is on."""
    if not is_enabled():
        return
    ts = time.strftime("%H:%M:%S")
    print(f"[DEBUG {ts}][{category}] {message}", flush=True)


def log_exception(category: str, exc: Exception, context: str = ""):
    """Log an exception with traceback (only when debugging is on)."""
    if not is_enabled():
        return
    import traceback
    ts = time.strftime("%H:%M:%S")
    ctx = f" ({context})" if context else ""
    print(f"[DEBUG {ts}][{category}] EXCEPTION{ctx}: {exc}", flush=True)
    traceback.print_exc()
