class VoiceCache:

    def __init__(self):

        self.cache = {}

    def update(

        self,

        member,

        channel

    ):

        self.cache[member.id] = channel

    def remove(

        self,

        member

    ):

        self.cache.pop(

            member.id,

            None

        )

    def get(

        self,

        member

    ):

        return self.cache.get(

            member.id

        )


voice_cache = VoiceCache()