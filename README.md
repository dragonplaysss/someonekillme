# Shorekeeper Revival

Python Discord bot with moderation, verification, logging, and music cogs.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Put your real Discord bot token in `.env`, then run:

```powershell
python main.py
```

## Oracle free cloud setup

On Ubuntu/Debian Oracle instances:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip ffmpeg git
git clone YOUR_GITHUB_REPO_URL shorekeeper-revival
cd shorekeeper-revival
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
python main.py
```

`ffmpeg` is required for music playback. The bot token is intentionally not committed to GitHub, so the cloud machine must have its own `.env` file or `DISCORD_TOKEN` environment variable.

## systemd service example

Replace `/home/ubuntu/shorekeeper-revival` with your actual clone path:

```ini
[Unit]
Description=Shorekeeper Revival Discord Bot
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/shorekeeper-revival
EnvironmentFile=/home/ubuntu/shorekeeper-revival/.env
ExecStart=/home/ubuntu/shorekeeper-revival/.venv/bin/python /home/ubuntu/shorekeeper-revival/main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Check logs with:

```bash
journalctl -u shorekeeper -f
```
