# Shorekeeper Final Legacy Update

Shorekeeper is a discord.py bot built around cogs, mention commands, slash commands, persistent server config, tickets, verification, moderation, roles, welcome messages, divisions, applications, and FastFlag file classification.

This release is a maintenance and handoff update. It keeps legacy mention commands working while reducing the public slash command surface.

## Install

1. Install Python 3.11 or newer.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and set `DISCORD_TOKEN`.
4. Start the bot:

```bash
python main.py
```

## Visible Slash Commands

Only these commands are intended to remain visible by default:

- `/help`
- `/settings`
- `/status`
- `/enablecommands`
- `/disablecommands`

Legacy slash commands are controlled by modules and are hidden unless a module is enabled.

## Mention Commands

Mention commands keep the legacy style:

```text
@Shorekeeper keyword args ; extra
```

Examples:

- `@Shorekeeper verify @user ; reason`
- `@Shorekeeper health`
- `@Shorekeeper update`
- `@Shorekeeper application create ; https://forms.gle/example optional-token`
- `@Shorekeeper ffcheck` with an attached `.txt`, `.json`, or `ClientAppSettings.json`

## Modules

Use:

- `/status`
- `/enablecommands <module>`
- `/disablecommands <module>`
- `@Shorekeeper module debug <module>`
- `@Shorekeeper module disable <module>`
- `@Shorekeeper module recover`

Module states are stored per guild in `config.modules`.

See `MODULES.md` for the full module table and behavior.

## Application Engine

Applications are mention-only:

- `@Shorekeeper application create ; <google_form_url> [token]`
- `@Shorekeeper application verify [token]`
- `@Shorekeeper application review`
- `@Shorekeeper application close`

Data is stored in `config/applications.json`. Reviewer notifications are sent to the channel where the application was created.

## FastFlag Checker

FastFlag checks are mention-only and classification-only:

- `@Shorekeeper ffcheck <attachment>`
- `@Shorekeeper ff allow <pattern>`
- `@Shorekeeper ff warn <pattern>`
- `@Shorekeeper ff review <pattern>`

Rules live in `config/ff_rules.json`. This tool never labels a user as a cheater, exploiter, or auto-ban target.

## Health And Recovery

- `@Shorekeeper health` checks loaded cogs, extension count, RAM availability, missing configured channels, and webhook access.
- `@Shorekeeper module recover` attempts to reload missing module extensions and resync visible commands.
- `@Shorekeeper update` runs the legacy-safe migration flow and shows enabled modules.

## Test Checklist

- Start the bot with `python main.py`.
- Confirm `/status` shows module states.
- Confirm only core slash commands are visible by default.
- Run `/enablecommands divisions`, verify division slash commands appear, then `/disablecommands divisions`.
- Run legacy mention commands for verify, tickets, moderation, roles, and divisions.
- Upload a sample `ClientAppSettings.json` with `@Shorekeeper ffcheck`.
- Run `@Shorekeeper application create`, `verify`, `review`, and `close`.
- Run `@Shorekeeper health` and `@Shorekeeper update`.
