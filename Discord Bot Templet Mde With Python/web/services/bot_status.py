"""Bot liveness/status for the website -- bridge client.

Same public shape as before (``status`` singleton with online/guilds/
users/latency + ``to_dict()``), but the numbers come from the bot-side
bridge status endpoint instead of the live bot object. ``refresh()``
fails closed: when the bridge is down the bot reads as offline with
zero counts, never as stale good news.
"""

from web.services import bridge
from web.services.bridge import BridgeError, BridgeUnavailable


class BotStatus:

    def __init__(self):

        self.online = False

        self.guilds = 0

        self.users = 0

        self.latency = 0

    def refresh(self):
        """Pull fresh numbers from the bridge. Fail-closed on any error."""
        try:
            info = bridge.status()
        except (BridgeUnavailable, BridgeError):
            self.online = False
            self.guilds = 0
            self.users = 0
            self.latency = 0
            return self
        self.online = bool(info.get("ready"))
        try:
            self.guilds = int(info.get("guild_count") or 0)
        except (TypeError, ValueError):
            self.guilds = 0
        try:
            self.users = int(info.get("member_total") or 0)
        except (TypeError, ValueError):
            self.users = 0
        try:
            self.latency = int(info.get("latency_ms") or 0)
        except (TypeError, ValueError):
            self.latency = 0
        return self

    def to_dict(self):

        return {

            "online": self.online,

            "guilds": self.guilds,

            "users": self.users,

            "latency": round(self.latency)

        }


status = BotStatus()


def refresh_status():
    """Refresh the module-level singleton and return its dict shape."""
    return status.refresh().to_dict()
