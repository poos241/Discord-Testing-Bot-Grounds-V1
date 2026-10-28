# Adding a database table

Tables live in `data/DB/models.py`, access goes through
`data/DB/Storage/storage.py`. Three steps, following the existing pattern.

## 1. Define the table in `models.py`

```python
my_feature = sqlalchemy.Table(
    "my_feature", metadata,
    sqlalchemy.Column("guild_id", sqlalchemy.String, primary_key=True),
    sqlalchemy.Column("data", sqlalchemy.JSON),   # flexible JSON blob
    sqlalchemy.Column("created_at", sqlalchemy.DateTime,
                      nullable=False, server_default=func.now()),
    timestamp_column(),                            # auto updated_at
)
```

Conventions: per-server tables use `guild_id` as the primary key; other
tables use their own keys (`profiles` is keyed by `user_id`,
`voice_xp_users` by `(guild_id, user_id)`, `friendships` by the pair).
A `data` JSON column holds the actual payload so you rarely need
migrations — just add keys to the dict. Scalar columns work too (the
newer tables use them); either way, a new table is always safe because
`create_all()` creates it on boot — only new *columns* on existing
tables need the manual migration in `db.py` (see
[Data layer](./data-layer.md)).

Don't forget to import the table name in `storage.py`.

## 2. Add a get/save pair in `storage.py`

```python
from data.DB.models import my_feature

async def get_my_feature(guild_id: str):
    row = await database.fetch_one(
        my_feature.select().where(my_feature.c.guild_id == guild_id))
    return row["data"] if row else {}

async def save_my_feature(guild_id: str, data: dict):
    await database.execute(
        my_feature.insert()
        .values(guild_id=guild_id, data=data)
        .prefix_with("OR REPLACE")   # upsert: insert or overwrite
    )
```

`OR REPLACE` makes save an upsert — no separate "create vs update" logic.

## 3. Use it in a cog

```python
from data.DB.Storage.storage import get_my_feature, save_my_feature

data = await get_my_feature(str(ctx.guild.id))
data["wins"] = data.get("wins", 0) + 1
await save_my_feature(str(ctx.guild.id), data)
```

## When not to use SQLite

Short answer: don't reach for JSON for new features. JSON files were the
old home for game round state and similar blobs, but those all moved to
SQLite in October 2026 (see [Data layer](./data-layer.md)) — the only
standing JSON file is the notification bell's read state. If your data
is JSON-shaped and you want the lightest path, follow the store pattern
in `utils/json_sqlite_store.py` rather than a new file.
