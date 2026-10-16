from dataclasses import dataclass
from datetime import datetime


@dataclass
class LoggerEvent:

    guild_id: int

    category: str

    action: str

    title: str

    color: int

    embed: object

    created: datetime