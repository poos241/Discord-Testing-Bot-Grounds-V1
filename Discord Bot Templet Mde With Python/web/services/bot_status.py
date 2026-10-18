class BotStatus:

    def __init__(self):

        self.online = False

        self.guilds = 0

        self.users = 0

        self.latency = 0

    def to_dict(self):

        return {

            "online": self.online,

            "guilds": self.guilds,

            "users": self.users,

            "latency": round(self.latency)

        }


status = BotStatus()