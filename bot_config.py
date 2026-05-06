import os

from dotenv import load_dotenv

from cogs.server_config import PANEL_OWNER_ID


load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

# Compatibility exports for older disabled cogs. Active cogs read JSON directly.
OWNER_IDS = [PANEL_OWNER_ID]
ADMIN_ROLE_IDS = []
MOD_ROLE_IDS = []
MUSIC_CHANNEL_ID = 0
LOG_CHANNEL_ID = 0
VERIFY_STAFF_ROLE_ID = 0
UNVERIFIED_ROLE_ID = 0
VERIFIED_ROLE_IDS = []
