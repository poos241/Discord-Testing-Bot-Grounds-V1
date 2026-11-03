"""Single access point to Discord state for the website process.

Split version (BRIDGE_CONTRACT.md section 5): the website no longer
holds a live bot object. There is no gateway login in this process.

- ``discord_state.bot`` / ``get_bot()`` always return None.
- ``discord_state.ready`` reflects bridge reachability (cached 5 s
  inside bridge.bot_is_ready()).
- ``run_coro_threadsafe(coro)`` delegates to the website's own local
  loop (web/services/local_loop.py), keeping the same signature so
  pure-DB async storage call sites work unchanged. It returns a
  concurrent.futures.Future, as before.

Any missed live-Discord call site fails loudly instead of silently:
its Discord objects are gone (bot is None), which is what we want
for testing -- the bridge client is the only way to reach Discord.
"""

import concurrent.futures
import threading

from web.services import bridge
from web.services.local_loop import run_async as _local_run_async


class _DiscordState:
    def __init__(self):
        self.bot = None

    @property
    def ready(self):
        """True when the bot-side bridge reports the bot is ready."""
        try:
            return bool(bridge.bot_is_ready())
        except Exception:
            return False

    def get_bot(self):
        """Compatibility accessor. Always None now -- no live bot object."""
        return None

    def is_ready(self):
        """True when the bot-side bridge reports the bot is ready."""
        return self.ready

    def set_bot(self, bot):
        """Kept for create_app() compat. The website no longer holds a
        live bot object, so any object passed here is discarded."""
        self.bot = None
        if bot is not None:
            print("[WARN] discord_state.set_bot called with a live bot "
                  "object; the website no longer holds one (bridge "
                  "split) -- ignoring it.")

    @property
    def loop(self):
        """The website's local loop (pure-DB async work only)."""
        try:
            from web.services.local_loop import get_loop

            return get_loop()
        except Exception:
            return None


discord_state = _DiscordState()


def run_coro_threadsafe(coro):
    """Run a coroutine on the website's local loop from a web thread.

    Returns a concurrent.futures.Future. Call .result(timeout=...) to
    wait, exactly as before. Only pure-DB/storage coroutines belong
    here -- a live-Discord coroutine has no bot loop to run on any
    more and will fail loudly, which is intentional.
    """
    future = concurrent.futures.Future()

    def _run():
        try:
            future.set_result(_local_run_async(coro, timeout=60))
        except BaseException as exc:  # noqa: BLE001 - relay to .result()
            if not future.done():
                future.set_exception(exc)

    threading.Thread(target=_run, daemon=True, name="web-run-coro").start()
    return future
