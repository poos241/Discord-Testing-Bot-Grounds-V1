from web.services.logger_db import logger_db as database


class StatisticsService:

    def message_deleted(self, guild_id: int):
        """
        FIXED: Added this missing attribute method to resolve the AttributeError.
        Saves a deleted message tracking transaction into the unified database.
        """
        try:
            database.save_event_from_bot(
                guild_id=int(guild_id),
                category="messages",
                action="delete",
                payload={
                    "action": "delete",
                    "description": f"Message deleted in server {guild_id}"
                }
            )
        except Exception as e:
            print(f"⚠️ Failed to track message deletion statistic: {e}")

    def get_global_stats(self):

        rows = database.latest_global_events(5000)

        stats = {
            "total": 0,
            "messages": 0,
            "members": 0,
            "roles": 0,
            "voice": 0,
            "server": 0,
            "channels": 0,
            "other": 0,
        }

        event_types = {}

        for row in rows:

            category = row[2] or "other"
            event_name = row[4] or "unknown"

            stats["total"] += 1

            if category not in stats:
                stats["other"] += 1
            else:
                stats[category] += 1

            event_types[event_name] = (
                event_types.get(event_name, 0) + 1
            )

        return {
            "stats": stats,
            "event_types": event_types,
        }


    def get_guild_stats(self, guild_id):

        rows = database.latest_global_events(5000)

        guild_id = int(guild_id)

        stats = {
            "total": 0,
            "messages": 0,
            "members": 0,
            "roles": 0,
            "voice": 0,
            "server": 0,
            "channels": 0,
            "other": 0,
        }

        event_types = {}

        for row in rows:

            row_guild_id = row[1]

            if row_guild_id != guild_id:
                continue

            category = row[2] or "other"
            event_name = row[4] or "unknown"

            stats["total"] += 1

            if category not in stats:
                stats["other"] += 1
            else:
                stats[category] += 1

            event_types[event_name] = (
                event_types.get(event_name, 0) + 1
            )

        return {
            "guild_id": str(guild_id),
            "stats": stats,
            "event_types": event_types,
        }


    def get_recent_events(
        self,
        guild_id=None,
        limit=25
    ):

        rows = database.latest_global_events(
            max(limit * 5, 100)
        )

        results = []

        for row in rows:

            if guild_id is not None:

                if row[1] != int(guild_id):
                    continue

            results.append({

                "id": row[0],

                "guild_id":
                    str(row[1]),

                "category":
                    row[2] or "unknown",

                "action":
                    row[3] or "",

                "event":
                    row[4] or "unknown",

                "timestamp":
                    row[5] or "",

                "created":
                    row[6] or 0,

            })

            if len(results) >= limit:
                break

        return results


statistics = StatisticsService()
