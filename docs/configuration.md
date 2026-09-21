# Shorekeeper configuration

Runtime configuration lives in `cogs/moderation/data2/server_config.json` and is
loaded via `cogs/server_config.py` (`load_config` / `get_guild_config`
/ `update_guild_config`). Writes are atomic (temp file + `os.replace`) and
non-destructive: unknown keys and existing values are preserved.

## Required environment variables

| Variable        | Required | Default        | Notes                                            |
| --------------- | -------- | -------------- | ------------------------------------------------ |
| `DISCORD_TOKEN` | yes      | —              | Bot client token. `main()` raises if missing.    |
| `MONGODB_URI`   | yes      | —              | Raised at first DB use if missing.               |
| `MONGODB_DB`    | no       | `shorekeeper`  | Mongo database name.                             |

Load them from a `.env` file in the project root (auto-loaded by `main.py` via
`python-dotenv`). Only the Panel Owner (see `cogs/server_config.py`) or a server
owner can mutate protection-critical settings.

## Anti-Nuke

Anti-Nuke is **off by default** for every guild
(`DEFAULT_GUILD["anti_nuke"]["enabled"] == False`, `mode == "monitor"`). It can
be toggled and configured from Discord with these owner-only slash commands:

| Command            | Description                                                                 |
| ------------------ | -------------------------------------------------------------------------- |
| `/antinukeenable`  | Enable Anti-Nuke protection for this server (defaults to `monitor` mode).  |
| `/antinukedisable` | Disable Anti-Nuke protection for this server.                              |
| `/antinukemode`    | Set the mode: `monitor` (log/alert only, never punishes) or `enforcement`. |

The full live status is always visible with `/settings` (Anti-Nuke field).

### Behaviour summary (see `cogs/core/anti_nuke.py`)

- **Disabled by default** -> `evaluate_bot_addition` / `evaluate_mass_action`
  short-circuit with `*_disabled` and do nothing.
- **Monitor mode** (`mode != "enforcement"`) -> events are recorded and alerted
  but no bot is removed and no member is kicked/banned.
- **Enforcement mode** -> unauthorized bot additions and rate-threshold
  mass-actions trigger removal/punishment and optional lockdown.
- **Bot-add allowlist / configured admins** -> bots in `trusted_bot_ids` and
  additions by `trusted_user_ids` / `trusted_role_ids` / configured `admin_ids`
  / `admin_roles` are treated as authorized (no punishment) for bot additions.
  Mass-action rate alarms still watch every actor, including admins.
- **Ambiguous audit attribution** -> if Discord audit logs cannot uniquely
  identify who added a bot (`actor is None`), the action is **not** punished
  (only flagged), preventing false-positive kicks on a server owner.

## Moderation hierarchy protection

Every destructive action (ban, kick, mute, warn, purge, role changes via
`@Shorekeeper giverole`/`removerole`/`verify`) runs through the central
authorization pipeline in `cogs/core/authz.py` before any Discord API call:
guild activation -> module activation -> actor authorization -> Discord
permission check -> actor hierarchy -> bot permission check -> bot hierarchy.
A failed check returns a themed denial embed (no API side-effect).
