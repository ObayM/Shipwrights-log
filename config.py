import os
import logging

from dotenv import load_dotenv

load_dotenv()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("huddle-bot")

SLACK_BOT_TOKEN: str = os.environ["SLACK_BOT_TOKEN"]
SLACK_APP_TOKEN: str = os.environ["SLACK_APP_TOKEN"]

HUDDLE_CHANNEL_ID: str = os.environ["HUDDLE_CHANNEL_ID"]
LOG_CHANNEL_ID: str = os.environ["LOG_CHANNEL_ID"]

SW_API_URL: str = os.environ.get(
    "SW_API_URL", "https://review.hackclub.com/api/admin/ship-certs-log"
)
SW_API_KEY: str = os.environ["SW_API_KEY"]

POLL_INTERVAL: int = int(os.environ.get("POLL_INTERVAL", "60"))
LEADERBOARD_INTERVAL: int = int(os.environ.get("LEADERBOARD_INTERVAL", "600"))
REDACTED_SENTINEL = "REDACTED"

CHANNEL_MEMBER_CACHE_TTL: int = 300  # 5 minutes
# BOT_ADMIN_ID: str = os.environ["BOT_ADMIN_ID"] Until @Nullskulls adds my new env on coolify
BOT_ADMIN_ID: str = "U07LKN2HXT3"
# HUDDLE_USERGROUP_ID: str = os.environ["HUDDLE_USERGROUP_ID"]
HUDDLE_USERGROUP_ID: str = "S09TJU4TT36"

