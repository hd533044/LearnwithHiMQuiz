import os

# Telegram Bot Token (with direct fallback)
BOT_TOKEN = os.environ.get("BOT_TOKEN", "8699323927:AAHr23eP9sOBRRCdOBFKKMwy_PK7kgc-MZo").strip()

# Official Channels
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@learnwithhim")
YOUTUBE_CHANNEL_URL = os.environ.get("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@learnwithhim")

# Database File & Directory Paths
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.environ.get("DATA_DIR", os.path.join(BASE_DIR, "data"))
DB_FILE = os.environ.get("DB_FILE", os.path.join(DATA_DIR, "quiz_bot.db"))

# Ensure data directory exists on startup
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR, exist_ok=True)

# Daily Question Limit Target (40 Questions)
DAILY_QUESTION_LIMIT = 40

# System Administrator Telegram IDs (Both IDs 1091057353 and 2070531704 added directly)
DEFAULT_ADMIN_IDS = [1091057353, 2070531704]
ENV_ADMINS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]
ADMIN_IDS = list(set(DEFAULT_ADMIN_IDS + ENV_ADMINS))