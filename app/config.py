import os

BOT_TOKEN = "8699323927:AAHr23eP9sOBRRCdOBFKKMwy_PK7kgc-MZo"
CHANNEL_USERNAME = "@learnwithhim"

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_FILE = os.path.join(DATA_DIR, "quiz_bot.db")

DAILY_QUESTION_LIMIT = 200

ADMIN_USER_ID = 123456789
ADMIN_IDS = [ADMIN_USER_ID]