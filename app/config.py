import os

# Telegram Bot Configuration
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@learnwithhim")
YOUTUBE_CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@learnwithhim")

# System & Quota Settings
DAILY_QUESTION_LIMIT = int(os.getenv("DAILY_QUESTION_LIMIT", "40"))
DB_FILE = os.getenv("DB_FILE", "quiz_bot.db")

# Authorized Administrator Telegram IDs
ADMIN_IDS = ["1091057353", "2070531704"]