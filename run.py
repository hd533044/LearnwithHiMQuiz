import asyncio
import logging
import warnings
import time
from app.telegram_bot import build_application

# Silence verbosity
warnings.filterwarnings("ignore")
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)

async def start_bot_with_retry():
    while True:
        try:
            print("==================================================")
            print("🤖 Enterprise Computer Quiz Bot Starting...")
            
            app = build_application()
            await app.initialize()
            await app.start()
            
            # Start polling cleanly & drop stale connection conflicts
            await app.updater.start_polling(drop_pending_updates=True)
            
            print("✅ Bot is active and listening 24/7 for Telegram updates!")
            print("==================================================")
            
            while True:
                await asyncio.sleep(3600)

        except Exception as e:
            print(f"⚠️ Connection interrupted: {e}")
            print("🔄 Reconnecting in 5 seconds...")
            await asyncio.sleep(5)

def main():
    try:
        asyncio.run(start_bot_with_retry())
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Stopping bot cleanly...")

if __name__ == "__main__":
    main()