# Shorekeeper Revival

Python Discord bot with moderation, verification, logging, and a hardened Wavelink/Lavalink music path.

## Local setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python main.py
```

Put your real Discord bot token in `.env` before starting the bot.

## Production music architecture

```text
Discord Bot
-> Wavelink
-> Lavalink
-> LavaSrc / SoundCloud / HTTP direct streams
-> yt-dlp extraction fallback
-> FFmpeg playback inside Lavalink
```

The bot does not use `lavalink-youtube-plugin`, YouTube OAuth, refresh tokens, poToken, visitorData, or IPv6 rotate-on-ban configs. YouTube is handled only by controlled yt-dlp fallback paths with IPv4 forced.

## Oracle Ubuntu dependencies

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip openjdk-17-jre-headless ffmpeg libopus0 build-essential python3-dev git curl unzip
curl -fsSL https://deno.land/install.sh | sh
echo 'export PATH="$HOME/.deno/bin:$PATH"' >> ~/.profile
export PATH="$HOME/.deno/bin:$PATH"
git clone YOUR_GITHUB_REPO_URL shorekeeper-revival
cd shorekeeper-revival
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
nano .env
```

Required Python packages are in `requirements.txt`:

```text
discord.py[voice]>=2.4,<3
python-dotenv
aiohttp
yt-dlp>=2026.3.17
yt-dlp-ejs
PyNaCl>=1.5,<2
audioop-lts; python_version >= "3.13"
wavelink>=3.5.2,<4
```

If YouTube changes again before a new pinned release is published, update yt-dlp first:

```bash
source /home/ubuntu/shorekeeper-revival/.venv/bin/activate
python -m pip install --upgrade "yt-dlp>=2026.3.17"
yt-dlp --version
deno --version
```

`yt-dlp` now needs an external JavaScript runtime for full YouTube signature and n-challenge solving. Deno is the recommended runtime; `yt-dlp-ejs` plus `--remote-components ejs:github` are configured so parser/challenge updates do not require a bot code change.

## Environment

```bash
DISCORD_TOKEN=put-your-discord-bot-token-here
MUSIC_BACKEND=wavelink
MUSIC_SEARCH_PROVIDER=soundcloud
LAVALINK_URI=http://127.0.0.1:2333
LAVALINK_PASSWORD=youshallnotpass
YTDLP_SOURCE_ADDRESS=0.0.0.0
YTDLP_EXECUTABLE=yt-dlp
YTDLP_TIMEOUT=35
MUSIC_MAX_RECOVERY_ATTEMPTS=5
MUSIC_NODE_CONNECT_ATTEMPTS=3
MUSIC_LOG_LEVEL=INFO
```

Optional:

```bash
YTDLP_COOKIES_FILE=/home/ubuntu/shorekeeper-revival/cookies.txt
SPOTIFY_CLIENT_ID=
SPOTIFY_CLIENT_SECRET=
DEEZER_ARL=
DEEZER_ENABLED=false
DEEZER_MASTER_KEY=
```

Cookies must be Netscape-format browser-exported cookies. The bot logs whether the file exists, has the Netscape header, contains YouTube cookie rows, and appears to include auth cookies. Keep `cookies.txt` private.

Deezer is disabled by default because LavaSrc refuses to start without a valid `DEEZER_MASTER_KEY`. Set `DEEZER_ENABLED=true`, `DEEZER_MASTER_KEY`, and `DEEZER_ARL` together before using Deezer fallback.

## Lavalink

Install and start Lavalink with this repo's `lavalink/application.yml`:

```bash
mkdir -p /home/ubuntu/lavalink/plugins
cd /home/ubuntu/lavalink
wget -O Lavalink.jar https://github.com/lavalink-devs/Lavalink/releases/latest/download/Lavalink.jar
cp /home/ubuntu/shorekeeper-revival/lavalink/application.yml ./application.yml
rm -f ./plugins/youtube-plugin-*.jar
rm -f ./plugins/lavasrc-plugin-*.jar
java -Djava.net.preferIPv4Stack=true -Djava.net.preferIPv6Addresses=false -jar Lavalink.jar
```

Expected startup: Lavalink downloads `com.github.topi314.lavasrc:lavasrc-plugin:4.8.1`; no `youtube-plugin` should appear in the logs or `plugins/` directory.

## systemd services

`/etc/systemd/system/lavalink.service`:

```ini
[Unit]
Description=Lavalink
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/lavalink
EnvironmentFile=/home/ubuntu/shorekeeper-revival/.env
ExecStart=/usr/bin/java -Djava.net.preferIPv4Stack=true -Djava.net.preferIPv6Addresses=false -jar /home/ubuntu/lavalink/Lavalink.jar
Restart=always
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

`/etc/systemd/system/shorekeeper.service`:

```ini
[Unit]
Description=Shorekeeper Revival Discord Bot
After=network-online.target lavalink.service
Wants=network-online.target lavalink.service

[Service]
Type=simple
WorkingDirectory=/home/ubuntu/shorekeeper-revival
EnvironmentFile=/home/ubuntu/shorekeeper-revival/.env
ExecStart=/home/ubuntu/shorekeeper-revival/.venv/bin/python /home/ubuntu/shorekeeper-revival/main.py
Restart=always
RestartSec=10
LimitNOFILE=65535

[Install]
WantedBy=multi-user.target
```

Start:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now lavalink shorekeeper
sudo systemctl restart lavalink shorekeeper
```

Logs:

```bash
journalctl -u lavalink -n 160 --no-pager
journalctl -u shorekeeper -f
```

## Playback flow

Plain searches try SoundCloud first, then LavaSrc Spotify, Apple Music, and Deezer search mirrors. If those fail or playback crashes, the bot regenerates a direct stream with yt-dlp using multiple YouTube client profiles and search forms, then asks Lavalink to play the direct HTTP stream. Failed tracks are retried through alternate providers without dropping the queue; unrecoverable tracks are skipped safely and the next queued item is loaded.

YouTube links skip Lavalink YouTube parsing entirely and go straight to yt-dlp direct-stream extraction.

## Oracle checks

```bash
curl -4I https://www.youtube.com/generate_204
curl -4I https://music.youtube.com
curl -4I https://api-v2.soundcloud.com
yt-dlp --force-ipv4 --source-address 0.0.0.0 -F "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
ffmpeg -version
```

Oracle/cloud IPs can still be blocked by YouTube. When that happens, the bot uses SoundCloud/LavaSrc mirrors first and yt-dlp cookies as the last YouTube rescue path. No software-only change can make an Oracle datacenter IP behave exactly like a residential IP.
