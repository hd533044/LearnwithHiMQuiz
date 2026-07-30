import os
import logging

# Base directory definition
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

# Telegram Bot Configuration with hardcoded fallback if env var is delayed
DEFAULT_TOKEN = "8699323927:AAHr23eP9sOBRRcD0BFKKMwy_PK7kgc-MZo"
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip() or DEFAULT_TOKEN

if not BOT_TOKEN:
    logging.warning("⚠️ BOT_TOKEN IS EMPTY! Please verify environment settings on Render.")

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
CHANNEL_USERNAME = os.getenv("CHANNEL_USERNAME", "@learnwithhim")
YOUTUBE_CHANNEL_URL = os.getenv("YOUTUBE_CHANNEL_URL", "https://www.youtube.com/@learnwithhim")

# System & Quota Settings
DAILY_QUESTION_LIMIT = int(os.getenv("DAILY_QUESTION_LIMIT", "40"))
DB_FILE = os.getenv("DB_FILE", os.path.join(DATA_DIR, "quiz_bot.db"))

# Authorized Administrator Telegram IDs
ADMIN_IDS = ["1091057353", "2070531704"]