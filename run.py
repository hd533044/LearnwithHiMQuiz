import asyncio
import logging
import warnings
import sys
from app.telegram_bot import build_application

# Completely silence deprecation warnings and HTTP/polling logs
warnings.filterwarnings("ignore")
logging.getLogger("httpx").setLevel(logging.CRITICAL)
logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("telegram.ext").setLevel(logging.CRITICAL)
logging.getLogger().setLevel(logging.CRITICAL)

async def main_async():
    print("==================================================")
    print("🤖 Enterprise Computer Quiz Bot Starting...")
    
    app = build_application()
    
    await app.initialize()
    await app.start()
    
    # Start polling cleanly & drop stale connection conflicts
    await app.updater.start_polling(drop_pending_updates=True)
    
    print("✅ Bot is active and listening for Telegram updates!")
    print("==================================================")
    
    try:
        while True:
            await asyncio.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        print("\n🛑 Stopping bot cleanly...")
    finally:
        await app.updater.stop()
        await app.stop()
        await app.shutdown()

def main():
    try:
        asyncio.run(main_async())
    except (KeyboardInterrupt, SystemExit):
        pass

if __name__ == "__main__":
    main()