class MessageFormatter:

    @staticmethod
    def attachments(message):

        if not message.attachments:

            return None

        lines = []

        for attachment in message.attachments:

            lines.append(

                f"📎 [{attachment.filename}]({attachment.url})"

            )

        return "\n".join(lines)

    @staticmethod
    def stickers(message):

        if not message.stickers:

            return None

        return "\n".join(

            sticker.name

            for sticker in message.stickers

        )

    @staticmethod
    def content(message):

        if message.content:

            return message.content

        return "*No message content.*"