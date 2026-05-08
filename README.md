# Shorekeeper Revival

Discord bot focused on moderation, tickets, welcome/goodbye visuals, embeds/webhooks, and vibe leveling.

This README is the handoff guide for staff/admins so they can understand exactly how Shorekeeper works.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Put your real Discord bot token in `.env` before starting.

## VPS setup (Ubuntu quickstart)

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git
git clone YOUR_REPO_URL shorekeeper-revival
cd shorekeeper-revival
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

## Environment

```bash
DISCORD_TOKEN=put-your-discord-bot-token-here
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=shorekeeper
GHOST_OWNER_ID=708390973712891976
TICKET_STAFF_ROLE_NAME=Staff
```

## Permission model

Shorekeeper has multiple permission buckets:

- `panel owner`: hardcoded `PANEL_OWNER_ID` in `cogs/server_config.py`
- `owner_ids`: per-server IDs stored in JSON config (`owner_ids`)
- `admin`: any of:
  - Discord Administrator permission
  - listed in `admin_roles` config
  - panel owner
- `mod`: any of:
  - admin
  - listed in `mod_roles` config

Use `@Shorekeeper whoami` to view your live permission state.

## Config storage

- JSON per-server config: `cogs/moderation/data2/server_config.json`
- MongoDB collections:
  - `warns`
  - `mod_actions`
  - `levels`
  - `nick_locks`
  - `bark_locks`
  - `uwu_locks`

## Core command style

Most moderation and utility commands use mention syntax:

```text
@Shorekeeper [keyword] [@user] ; [reason/args]
```

Examples:

```text
@Shorekeeper warn @user ; spam links
@Shorekeeper giverole @user ; Moderator | trusted helper
@Shorekeeper locknick @user ; Cool Name
```

`| reason` is optional in role commands:

```text
@Shorekeeper giverole @abc ; Moderator | trusted helper
@Shorekeeper removerole @abc ; 123456789012345678 | cleanup
```

## Moderation commands

All commands below are mention-based.

- `@Shorekeeper kick @user ; reason`
- `@Shorekeeper ban @user ; reason`
- `@Shorekeeper unban @user_or_id ; reason`
- `@Shorekeeper mute @user ; reason`
- `@Shorekeeper unmute @user ; reason`
- `@Shorekeeper warn @user ; reason`
- `@Shorekeeper warns [@user]`

Behavior:

- Sends a moderation DM to punished user (server, action, reason).
- Logs actions to `mod_logs` channel (fallback: `logging`).
- Stores warns and mod actions in MongoDB.

## Verify system

- `@Shorekeeper verify @user ; optional reason`

Uses JSON config keys:

- `verify_staff_roles`
- `verified_roles`
- `unverified_role`

## Nick lock (admin-based)

- `@Shorekeeper locknick @user ; new nickname`
- `@Shorekeeper unlocknick @user ; reason`
- `@Shorekeeper nicklocks`

Notes:

- Nick lock auto-reapplies when user changes nick.
- Requires bot role hierarchy to be above target.

## Role tools

- `@Shorekeeper giverole @user ; role_name_or_id | optional reason`
- `@Shorekeeper removerole @user ; role_name_or_id | optional reason`

Works with exact role name or role ID.

## Owner/admin special tools

### Owner list management

- `@Shorekeeper owners`
- `@Shorekeeper setowner ; add 123456789012345678`
- `@Shorekeeper setowner ; remove 123456789012345678`

### Force nick tools

- `@Shorekeeper force ; nick @user | nickname`
- `@Shorekeeper force ; unnick @user`

### Fun locks (delete + replace messages)

- `@Shorekeeper barklock @user ; reason`
- `@Shorekeeper unbarklock @user ; reason`
- `@Shorekeeper uwulock @user ; reason`
- `@Shorekeeper unuwulock @user ; reason`
- `@Shorekeeper lockstatus @user`

Behavior:

- Bark lock: deletes user message and sends `bark`/`woof` randomly.
- UwU lock: deletes user message and reposts an uwu-fied version.

These are restricted to admin + owner_ids.

## Vibe (leveling) system

- Passive XP is gained by chatting.
- `@Shorekeeper vibe [@user]` shows:
  - XP
  - level
  - vibe status

Status ladder:

- Level 1+: `Newbie`
- Level 10+: `Regular`
- Level 25+: `Elite`
- Level 50+: `Legend`

## Ghost mode (owner command)

- `@Shorekeeper ghost`

Owner-only command to silently join your current voice channel (self-muted + self-deaf).

## Utility commands

- `@Shorekeeper ping`
- `@Shorekeeper avatar [@user]`
- `@Shorekeeper userinfo [@user]`
- `@Shorekeeper serverinfo`
- `@Shorekeeper config` (alias: `showconfig`, `verifyconfig`)
- `@Shorekeeper setverify ; key value`
- `@Shorekeeper whoami`
- `@Shorekeeper shorehelp`

`setverify` keys:

- `add_verify_staff <role_id_or_mention>`
- `remove_verify_staff <role_id_or_mention>`
- `add_verified <role_id_or_mention>`
- `remove_verified <role_id_or_mention>`
- `set_unverified <role_id_or_mention>`
- `set_logging <channel_id_or_mention>`
- `set_mod_logs <channel_id_or_mention>`

## Slash commands

- `/setupwelcome <channel>`
- `/setupgoodbye <channel>`
- `/ticketpanel`
- `/embed`
- `/webhook`

## Welcome / goodbye visuals

When configured, Shorekeeper sends visual embeds on join/leave with:

- GIF placeholder
- user avatar thumbnail
- message style:
  - `Welcome <@ID> username 🥰 Hope you enjoy your stay`

## Tickets

`/ticketpanel` posts a persistent button panel.

- User clicks **Open Ticket** -> private `ticket-XXXX` channel
- Visible to user + `TICKET_STAFF_ROLE_NAME` role
- **Close** button archives transcript to logs and deletes ticket

## Embed/webhook engine

- `/embed`: opens modal with Title, Description, Color, Image URL, Thumbnail URL
- `/webhook`: creates a webhook in current channel and returns URL

## Channel config keys

Current channel keys in JSON config:

- `blacklist`
- `logging`
- `mod_logs`
- `track`
- `welcome`
- `goodbye`
- `tickets`

## Notes

- Music/Lavalink system has been removed.
- Ensure bot role is high enough for moderation, nick, and role actions.
- For production, run Shorekeeper with a process manager (`systemd`, `pm2`, etc.).
