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

Conventions: `guild_id` is always the primary key (everything is
per-server), and a `data` JSON column holds the actual payload so you
rarely need migrations — just add keys to the dict.

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

If the data is a simple blob rewritten constantly (like game round state),
a JSON file via `config.load_json` is simpler — see
[Data layer](./data-layer.md). SQLite wins when the data is structured,
per-guild, and long-lived.
