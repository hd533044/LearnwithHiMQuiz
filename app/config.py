import os

# Telegram Bot Token
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")

# Official Channels
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@learnwithhim")
YOUTUBE_CHANNEL_URL = os.environ.get("YOUTUBE_CHANNEL_URL", "https://youtube.com/learnwithhim")

# Database File Path (Fixes the ImportError)
DB_FILE = os.environ.get("DB_FILE", "quiz_bot.db")

# Daily Question Limit Target (40 Questions)
DAILY_QUESTION_LIMIT = 40

# System Administrator Telegram IDs
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]