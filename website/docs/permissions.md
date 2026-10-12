# Permissions

Decorators in `config.py` wrap commands with permission checks. They reply
ephemerally and return `False` when the check fails:

```python
from config import admin_required, is_owner

@commands.slash_command(name="secret", description="Admins only")
@admin_required()
async def secret(self, ctx):
    ...

@commands.slash_command(name="kill", description="Owner only")
@is_owner()
async def kill(self, ctx):
    ...
```

Available decorators:

| Decorator | Who passes |
|---|---|
| `admin_required()` | Server administrators |
| `is_owner()` | IDs in `OWNER_IDS` in `config.py` |
| `Manage_messages_required()` | Members with Manage Messages |
| `Manage_channels_required()` | Members with Manage Channels |

`extra_help(text)` attaches a longer description to a command for
documentation purposes:

```python
@extra_help("Starts a server-wide XP multiplier event (2-5x, up to 24h).")
```
