"""Single access point to the live Discord bot object.

The Flask app is created via ``create_app(bot)`` in ``web/app.py``, which
calls :func:`discord_state.set_bot`. Every blueprint and service uses
``discord_state.bot`` instead of importing from ``core`` or ``bot``.

Threading note: the web server runs in a daemon thread beside the bot's
asyncio loop. *Reads* (get_guild, get_member, ...) are safe to call
directly. *Writes* (kick, ban, timeout, ...) must be scheduled onto the
bot's loop — use :func:`run_coro_threadsafe`.
"""

import asyncio


class _DiscordState:
    def __init__(self):
        self.bot = None
        self._loop = None

    @property
    def ready(self):
        return self.bot is not None

    def get_bot(self):
        """Compatibility accessor used by older blueprint code."""
        return self.bot

    def is_ready(self):
        """True when the bot is connected and its client reports ready."""
        if self.bot is None:
            return False
        try:
            return bool(self.bot.is_ready())
        except Exception:
            return True

    def set_bot(self, bot):
        self.bot = bot
        try:
            self._loop = asyncio.get_running_loop()
        except RuntimeError:
            self._loop = getattr(bot, "loop", None)

    @property
    def loop(self):
        if self._loop is not None:
            return self._loop
        return getattr(self.bot, "loop", None)


discord_state = _DiscordState()


def run_coro_threadsafe(coro):
    """Schedule a coroutine on the bot's event loop from a web thread.

    Returns a concurrent.futures.Future. Call .result(timeout=...) to wait.
    """
    loop = discord_state.loop
    if loop is None:
        raise RuntimeError("Bot event loop is not available")
    return asyncio.run_coroutine_threadsafe(coro, loop)
