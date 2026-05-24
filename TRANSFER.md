# Shorekeeper Transfer Notes

This bot is ready for long-term handoff without a rewrite.

## What To Keep Stable

- `main.py` owns startup, cog loading, and slash sync.
- `cogs/server_config.py` owns persistent guild config and cached reads.
- `cogs/module_registry.py` maps modules to commands and extensions.
- `cogs/trigger_parser.py` keeps mention-command compatibility and blocks disabled modules.
- `config/ff_rules.json` lets admins update FastFlag classification rules without code changes.

## First Run

1. Install dependencies with `pip install -r requirements.txt`.
2. Set `DISCORD_TOKEN` in `.env`.
3. Start with `python main.py`.
4. In Discord, run `/status`.
5. Run `@Shorekeeper health`.
6. Run `@Shorekeeper update` once per guild after transfer.

## Enabling Legacy Slash Commands

By default, only the five core slash commands are visible. To temporarily expose an older slash module:

```text
/enablecommands divisions
```

To hide it again while keeping mention commands:

```text
/disablecommands divisions
```

To fully stop a module in one guild:

```text
@Shorekeeper module disable divisions
```

## Recovery

If commands disappear or a cog fails after a deploy:

```text
@Shorekeeper module recover
@Shorekeeper health
```

If Python reports NUL bytes in a source file:

```bash
python scripts/fix_nullbytes.py cogs/tickets.py
```

## FastFlag Rule Updates

Rules are stored in `config/ff_rules.json`.

Admins can add rules in Discord:

```text
@Shorekeeper ff allow ^FIntGraphics.*
@Shorekeeper ff warn .*Experiment.*
@Shorekeeper ff review .*Movement.*
```

The checker only classifies files as `SAFE`, `WARNING`, `UNSUPPORTED`, or `REVIEW`.

## Application Flow

Open:

```text
@Shorekeeper application create ; https://forms.gle/example optional-token
```

Applicant verifies:

```text
@Shorekeeper application verify optional-token
```

Review:

```text
@Shorekeeper application review
```

Close:

```text
@Shorekeeper application close
```

## Release Checklist

- `python -m py_compile main.py cogs/module_manager.py cogs/applications.py cogs/ff_checker.py cogs/module_registry.py cogs/server_config.py cogs/trigger_parser.py`
- `/status` returns module states.
- Only `/help`, `/settings`, `/status`, `/enablecommands`, and `/disablecommands` are visible by default.
- Mention commands still work for tickets, verify, roles, moderation, and divisions.
- `@Shorekeeper ffcheck` accepts `.txt`, `.json`, and `ClientAppSettings.json`.
- `@Shorekeeper health` returns loaded cog and channel checks.
- `@Shorekeeper update` completes and shows enabled modules.
