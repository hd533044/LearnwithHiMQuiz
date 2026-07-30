import os

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHANNEL_USERNAME = os.environ.get("CHANNEL_USERNAME", "@learnwithhim")
YOUTUBE_CHANNEL_URL = os.environ.get("YOUTUBE_CHANNEL_URL", "https://youtube.com/learnwithhim")

# Updated Default Daily Limit to 40 Questions
DAILY_QUESTION_LIMIT = 40

# Admin IDs list
ADMIN_IDS = [int(x.strip()) for x in os.environ.get("ADMIN_IDS", "").split(",") if x.strip().isdigit()]