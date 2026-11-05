"""Kuma heartbeat: push a heartbeat to Uptime Kuma so it can show the bot
as UP/DOWN.

The bot is a separate process with no HTTP endpoint of its own (the bridge
is localhost-only and the bot-status pages need a login), so the bot pushes
its own heartbeat to Kuma instead of Kuma pulling it.

Setup (done by Emily in Kuma, not by the bot):
  1. In Uptime Kuma, create a monitor of type Push. Set its Heartbeat
     Interval to 60s. Kuma shows a push URL like
     http://127.0.0.1:3001/api/push/<key>.
  2. Put that URL in the bot's .env as KUMA_PUSH_URL=<the push URL>.
     The URL contains a key — treat it like a secret: never commit it,
     never share it.
  3. Restart the bot (/restart_bot or the dashboard Restart bot button).

The bot pushes every KUMA_PUSH_INTERVAL_SECONDS (default 30). The push
interval must stay shorter than Kuma's Heartbeat Interval (30s push vs
60s Kuma interval) so normal jitter never flaps the monitor.

If KUMA_PUSH_URL is unset, the heartbeat is disabled and the cog logs
one line at startup. A failed push is logged and the loop keeps going —
one failed push never kills the loop.
"""

import os

import aiohttp
from discord.ext import commands, tasks

DEFAULT_INTERVAL_SECONDS = 30.0
PUSH_TIMEOUT_SECONDS = 10


def _push_interval_seconds():
    """Read the push interval from the environment (default 30s).

    Falls back to the default for a missing, non-numeric, zero, or
    negative value. No upper clamp — the operator picks the interval.
    """
    raw = os.getenv("KUMA_PUSH_INTERVAL_SECONDS", str(DEFAULT_INTERVAL_SECONDS))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL_SECONDS
    if value <= 0:
        return DEFAULT_INTERVAL_SECONDS
    return value


class KumaHeartbeat(commands.Cog):
    """Push a heartbeat to Uptime Kuma on a fixed interval."""

    def __init__(self, bot):
        self.bot = bot
        self.push_url = (os.getenv("KUMA_PUSH_URL") or "").strip()
        self.interval = _push_interval_seconds()
        if not self.push_url:
            print("[KUMA] Kuma push URL not set (KUMA_PUSH_URL) — heartbeat disabled")
            return
        print(f"[KUMA] Heartbeat enabled — pushing every {self.interval:g}s")
        self.heartbeat_loop.change_interval(seconds=self.interval)
        self.heartbeat_loop.start()

    async def _push_once(self):
        """One heartbeat push. Never raises; never logs the URL or its key.

        Kuma answers 2xx for a good push. A non-2xx (for example 404 for
        an unknown key) is logged by status code only. Transport errors
        are logged by exception type only — aiohttp error reprs can carry
        the request URL, and the URL holds the push key.
        """
        try:
            timeout = aiohttp.ClientTimeout(total=PUSH_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(self.push_url) as resp:
                    if 200 <= resp.status < 300:
                        return
                    print(f"[KUMA] Push failed: Kuma returned HTTP {resp.status}")
                    return
        except Exception as e:  # noqa: BLE001 - the loop must never die
            print(f"[KUMA] Push failed: {type(e).__name__}")

    @tasks.loop(seconds=DEFAULT_INTERVAL_SECONDS)
    async def heartbeat_loop(self):
        if self.bot.is_closed():
            return
        try:
            await self._push_once()
        except Exception as e:  # noqa: BLE001 - belt and braces, _push_once never raises
            print(f"[KUMA] Push failed: {type(e).__name__}")

    @heartbeat_loop.before_loop
    async def before_heartbeat_loop(self):
        await self.bot.wait_until_ready()


def setup(bot):
    bot.add_cog(KumaHeartbeat(bot))
