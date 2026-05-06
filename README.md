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
sudo apt install -y python3 python3-venv python3-pip ffmpeg libopus0 build-essential python3-dev git
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

`ffmpeg`, `libopus0`, and `PyNaCl` are required for music playback. `PyNaCl` is installed by `requirements.txt`; the system build packages above are included so it can install even if a wheel is not available for your Python version. The bot token is intentionally not committed to GitHub, so the cloud machine must have its own `.env` file or `DISCORD_TOKEN` environment variable.

## Lavalink/Wavelink Music

The recommended cloud backend is Wavelink with a local Lavalink server. In `.env`:

```bash
MUSIC_BACKEND=wavelink
MUSIC_SEARCH_PROVIDER=youtube
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=youshallnotpass
```

Install Java and download Lavalink:

```bash
sudo apt update
sudo apt install -y openjdk-17-jre-headless
mkdir -p ~/lavalink
cd ~/lavalink
wget -O Lavalink.jar https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar
cp /home/ubuntu/someonekillme/lavalink/application.yml ./application.yml
java -jar Lavalink.jar
```

Keep that terminal open for a quick test, or create a service after it starts successfully:

```ini
[Unit]
Description=Lavalink
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/lavalink
ExecStart=/usr/bin/java -jar /home/ubuntu/lavalink/Lavalink.jar
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Save as `/etc/systemd/system/lavalink.service`, then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lavalink
sudo systemctl restart shorekeeper
```

If the bot replies twice, two bot processes are running. Stop the manual one and restart only systemd:

```bash
pkill -f "python.*main.py"
sudo systemctl restart shorekeeper
```

## YouTube cloud blocking

YouTube sometimes blocks Oracle/cloud IPs with "Sign in to confirm you're not a bot." By default, the bot uses SoundCloud search for plain song names to avoid that. YouTube links can still be blocked unless cookies are configured.

Make sure `.env` contains:

```bash
MUSIC_SEARCH_PROVIDER=soundcloud
```

Export YouTube cookies from a browser where YouTube works, upload them to the server as `cookies.txt`, then add this to `.env`:

```bash
YTDLP_COOKIES_FILE=/home/ubuntu/shorekeeper-revival/cookies.txt
```

Keep `cookies.txt` private and do not commit it to GitHub.

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
