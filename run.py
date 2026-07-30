import asyncio
import logging
import warnings
import sys
import os
from app.config import BOT_TOKEN
from app.telegram_bot import build_application

# Configure logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)

async def start_bot_with_retry():
    clean_token = BOT_TOKEN.strip() if BOT_TOKEN else ""
    
    if not clean_token:
        print("❌ CRITICAL ERROR: BOT_TOKEN is empty! Please set BOT_TOKEN in Render Environment Variables.")
        sys.exit(1)

    while True:
        try:
            print("==================================================")
            print("🤖 Enterprise Computer Quiz Bot Starting...")
            print(f"🔑 Connecting with Bot Token ending in: ...{clean_token[-6:]}")
            
            app = build_application()
            await app.initialize()
            await app.start()
            
            # Start polling cleanly & drop stale connection conflicts
            await app.updater.start_polling(drop_pending_updates=True)
            
            print("✅ Bot is active and listening 24/7 for Telegram updates!")
            print("==================================================")
            
            # Keep running indefinitely
            while True:
                await asyncio.sleep(3600)

        except Exception as e:
            print(f"⚠️ Connection error: {e}")
            print("🔄 Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

def main():
    try:
        asyncio.run(start_bot_with_retry())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Stopping bot cleanly...")

if __name__ == "__main__":
    main()