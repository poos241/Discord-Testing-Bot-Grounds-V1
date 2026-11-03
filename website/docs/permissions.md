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

## Web dashboard

The dashboard has three tiers, resolved from the Discord permission
bitfield of the guild the user is in (`web/services/permissions.py`):
**viewer** (any member), **moderator** (Manage Messages or above),
**admin** (Manage Server / Administrator / owner). API routes gate on
the tier, and member-list, backup, and debug routes additionally
intersect the user's guild list with the bot's own guilds — being a
moderator of an unrelated server grants nothing.

Since October 2026, web mod actions no longer share one moderator tier:
each action needs its own Discord permission bit
(`require_guild_permission` in `web/security/decorators.py`):

| Action | Permission needed |
|---|---|
| Ban / tempban / unban | Ban Members |
| Kick | Kick Members |
| Timeout / remove timeout | Timeout Members |
| Warn, notes, watch, clear | Manage Messages |
| Rename | Manage Nicknames |
| Strip roles | Manage Roles |

Wiping a member's data needs the **admin** tier plus the member's user ID
re-typed in the request (`confirm`) — the client-side confirm dialog
alone is not enough. The debug APIs (`/api/debug/*`) and the debug panel
are staff-only (moderator tier on a bot guild, failing closed while the
bot is down), and the clear-logs endpoint takes a `which` value
(`web` / `bot` / `all`) instead of always wiping both logs.

**Server Home is admin-only (November 2026).** The server-home page
(`/server-home`) and its status API (`GET /api/server-home/status`)
used to be login-only, so any logged-in Discord user could read host
load, CPU temperature, RAM, disk, service up/down, bot guild/member
counts, and AdGuard + Portainer numbers. Both routes now require the
admin tier (the same `_require_admin()` helper as the restart route)
and fail closed while the bot is down — if the bot is ever down, the
page refuses even for an admin, by design.

**Gates after the split (November 2026).** Since the website no longer
shares a process with the bot, the staff/admin gates intersect the
user's guild list with the bot's guilds via the bridge
(`bridge.get_bot_guild_ids()`) instead of a live bot object. The
behavior is unchanged — a moderator of an unrelated server still gets
nothing, and every gate fails closed (403) when the bot or the bridge
is unreachable — but the check now costs one bridge call, so a down
bot means refused pages rather than a hang.
