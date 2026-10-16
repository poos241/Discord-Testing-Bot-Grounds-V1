import json
import os

CONFIG = "data/logger_channels.json"


def load():

    if not os.path.exists(CONFIG):

        with open(CONFIG, "w") as f:

            json.dump({}, f)

    with open(CONFIG) as f:

        return json.load(f)


def save(data):

    with open(CONFIG, "w") as f:

        json.dump(data, f, indent=4)


def set_channel(

    guild,

    category,

    channel

):

    data = load()

    guild = str(guild)

    data.setdefault(

        guild,

        {}

    )

    data[guild][category] = channel

    save(data)


def get_channel(

    guild,

    category

):

    data = load()

    guild = str(guild)

    if guild not in data:

        return None

    return data[guild].get(category)