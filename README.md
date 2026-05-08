# Shorekeeper Revival

Discord bot focused on moderation, tickets, welcome/goodbye visuals, webhooks, and vibe leveling.

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

## Environment

```bash
DISCORD_TOKEN=put-your-discord-bot-token-here
MONGODB_URI=mongodb://127.0.0.1:27017
MONGODB_DB=shorekeeper
GHOST_OWNER_ID=708390973712891976
TICKET_STAFF_ROLE_NAME=Staff
```

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
