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
MUSIC_SEARCH_PROVIDER=soundcloud
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=youshallnotpass
```

Plain song searches use SoundCloud first. If SoundCloud returns nothing or a
track fails during playback, the bot tries one YouTube fallback and then one
`yt-dlp` direct-stream rescue. It does not enqueue every search result as fake
fallback tracks.

Install Java and download Lavalink:

```bash
sudo apt update
sudo apt install -y openjdk-17-jre-headless
mkdir -p ~/lavalink
cd ~/lavalink
wget -O Lavalink.jar https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar
cp /home/ubuntu/shorekeeper-revival/lavalink/application.yml ./application.yml
rm -f ./plugins/youtube-plugin-*.jar
java -jar Lavalink.jar
```

The `rm -f` line clears stale cached youtube-plugin jars. On the next start,
Lavalink downloads the version declared in `application.yml`.

Keep that terminal open for a quick test, or create a service after it starts successfully:

```ini
[Unit]
Description=Lavalink
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/lavalink
EnvironmentFile=/home/ubuntu/shorekeeper-revival/.env
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

## YouTube Cloud Blocking

YouTube sometimes blocks Oracle/cloud IPs with "Sign in to confirm you're not a bot." By default, the bot uses SoundCloud search for plain song names to avoid that. YouTube links can still be blocked.

For `youtube-plugin` 1.18.1, the plugin config lives at top-level
`plugins.youtube`, while the dependency belongs under `lavalink.plugins`.
There is no valid `cookie:` or `cookies:` path in youtube-plugin 1.18.1, so
cookie settings in `application.yml` are ignored. Cookies are only for the
bot's `yt-dlp` fallback.

If you used the `google.com/device` OAuth flow, copy the printed refresh token
from the Lavalink log and persist it in `.env`:

```bash
YOUTUBE_OAUTH_ENABLED=true
YOUTUBE_OAUTH_REFRESH_TOKEN=paste-the-refresh-token-here
YOUTUBE_OAUTH_SKIP_INITIALIZATION=true
```

Then restart Lavalink. OAuth only helps youtube-plugin clients that support
OAuth, so the Lavalink config includes the `TV` playback client after `MUSIC`
and `WEB`.

For the separate `yt-dlp` rescue path, export YouTube cookies from a browser
where YouTube works, upload them to the server as `cookies.txt`, then add this
to `.env`:

```bash
YTDLP_COOKIES_FILE=/home/ubuntu/shorekeeper-revival/cookies.txt
```

Keep `cookies.txt` private and do not commit it to GitHub.

Quick VPS network checks:

```bash
curl -4I https://www.youtube.com/generate_204
curl -4I https://music.youtube.com
curl -4I https://api-v2.soundcloud.com
journalctl -u lavalink -n 120 --no-pager
```

If YouTube returns bot/login pages from Oracle, SoundCloud remains the stable
primary path and YouTube stays best-effort fallback.

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
