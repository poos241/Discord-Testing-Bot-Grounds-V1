import json
import os

ARCHIVE = "data/logger_archive.json"


def archive(data):

    if not os.path.exists(ARCHIVE):

        with open(ARCHIVE, "w") as f:

            json.dump([], f)

    with open(ARCHIVE, "r") as f:

        logs = json.load(f)

    logs.append(data)

    with open(ARCHIVE, "w") as f:

        json.dump(logs, f, indent=4)