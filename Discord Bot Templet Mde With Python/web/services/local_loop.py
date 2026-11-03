"""The website's own asyncio event loop (BRIDGE_CONTRACT.md section 5).

A daemon thread running its own asyncio loop, created lazily on first
use. This replaces the bot's loop for pure-DB async storage calls
(Class A call sites): ``run_coro_threadsafe`` in discord_state.py
delegates here, so storage helpers keep working unchanged in the
website process. Safe to call from any waitress thread.

Live-Discord calls must NOT run here -- they go through the bridge
(web/services/bridge.py). A lock collision in the website's aiosqlite
storage surfaces as an error to the route, which must return 503
(degraded), never crash.
"""

import asyncio
import threading

_lock = threading.Lock()
_loop = None
_thread = None


def _ensure_started():
    global _loop, _thread
    with _lock:
        if _loop is not None and _thread is not None and _thread.is_alive():
            return _loop
        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def _run():
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(
            target=_run, daemon=True, name="web-local-loop",
        )
        thread.start()
        ready.wait(timeout=10)
        _loop = loop
        _thread = thread
        return loop


def get_loop():
    """Return the local loop, starting its thread on first use."""
    return _ensure_started()


def run_async(coro, timeout=15):
    """Run a coroutine on the local loop and return its result.

    Raises TimeoutError on timeout (the coroutine keeps running in the
    background until it finishes, same as the old bot-loop behaviour).
    Raises RuntimeError if called from the local-loop thread itself
    (that would deadlock) -- callers on that thread must await directly.
    """
    loop = _ensure_started()
    if threading.current_thread() is _thread:
        raise RuntimeError(
            "run_async called from the local-loop thread itself; "
            "await the coroutine directly instead."
        )
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    try:
        return future.result(timeout=timeout)
    except TimeoutError:
        future.cancel()
        raise
