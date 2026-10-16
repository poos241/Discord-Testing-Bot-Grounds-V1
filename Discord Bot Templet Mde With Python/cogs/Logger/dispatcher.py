class Dispatcher:

    def __init__(self):

        self.events = {}

    def register(

        self,

        event,

        callback

    ):

        self.events.setdefault(

            event,

            []

        ).append(

            callback

        )

    async def dispatch(

        self,

        event,

        *args,

        **kwargs

    ):

        if event not in self.events:

            return

        for callback in self.events[event]:

            await callback(

                *args,

                **kwargs

            )


dispatcher = Dispatcher()