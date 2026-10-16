from collections import OrderedDict


class MessageCache:

    def __init__(self, limit=5000):

        self.limit = limit
        self.messages = OrderedDict()

    def add(self, message):

        self.messages[message.id] = message

        self.messages.move_to_end(message.id)

        while len(self.messages) > self.limit:

            self.messages.popitem(last=False)

    def get(self, message_id):

        return self.messages.get(message_id)

    def remove(self, message_id):

        self.messages.pop(message_id, None)

    def clear(self):

        self.messages.clear()


cache = MessageCache()