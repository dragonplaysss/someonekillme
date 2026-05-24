# Shorekeeper Modules

Module state is persisted per guild under `config.modules` in `cogs/moderation/data2/server_config.json`.

Example:

```json
{
  "modules": {
    "divisions": "hidden",
    "tickets": "active",
    "welcome": "disabled"
  }
}
```

## States

- `ACTIVE`: module is loaded and slash commands are visible.
- `HIDDEN`: module is loaded, slash commands are hidden, mention commands still work.
- `DISABLED`: module commands are unavailable for that guild.
- `DEBUG`: module is loaded, slash commands are visible, and status surfaces it as debug.

Modules with slash commands default to `HIDDEN` so the long-term visible command list stays small. Legacy mention-only modules default to `ACTIVE`. New handoff modules such as `applications` and `ff` default to `DISABLED` and must be enabled manually.

## Commands

- `/enablecommands <module>` sets the module to `ACTIVE` and syncs slash commands.
- `/disablecommands <module>` sets the module to `HIDDEN` and syncs slash commands.
- `@Shorekeeper module disable <module>` sets the module to `DISABLED`.
- `@Shorekeeper module debug <module>` sets the module to `DEBUG`.
- `@Shorekeeper module recover` reloads missing extensions and resyncs.
- `/status` shows module state and load status.

## Built-In Modules

- `core`: `/help`, `/settings`, `/status`, `/enablecommands`, `/disablecommands`, plus health/update/recovery mention commands.
- `applications`: Google Forms application flow.
- `ff`: Roblox FastFlag file classifier.
- `divisions`: division registry and join/leave flow.
- `tickets`: ticket panel and ticket-channel mention tools.
- `welcome`: welcome/goodbye setup and member join/leave messages.
- `embed`: embed builder and webhook helper.
- `moderation`: ban, kick, mute, warn, purge, mod panel, nick lock, seal tools.
- `roles`: role grant/removal helpers.
- `misc`: utility/config/owner/fun-lock commands.
- `vibe`: vibe and ghost commands.
- `logger`: event logging listeners.

## Slash Command Mapping

`divisions`:

- `setupdivisions`
- `setupdivisionregistry`
- `setdivisionrequestchannel`
- `diviupdatewbh`
- `setdivisionbanner`
- `setdivisioncrest`
- `setmainerrole`
- `enablejoindivisions`
- `disablejoindivisions`
- `equalizedivisions`

`tickets`:

- `ticketpanel`

`welcome`:

- `setupwelcome`
- `setupgoodbye`
- `setwelcomegif`
- `setgoodbyegif`

`embed`:

- `embed`
- `webhook`

## Notes

The bot is one Discord process shared across guilds, so module extensions stay importable when another guild still needs them. Per-guild availability is enforced through the mention parser and per-guild slash command sync.
