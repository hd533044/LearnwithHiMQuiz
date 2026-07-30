import http.server
import socketserver
import os
import subprocess
import threading
import time
import urllib.request
import logging

logging.basicConfig(level=logging.INFO)

PORT = int(os.environ.get("PORT", 10000))
RENDER_EXTERNAL_URL = os.environ.get("RENDER_EXTERNAL_URL", "")

class HealthHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - Quiz Bot Active 24/7")

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_web_server():
    try:
        with socketserver.TCPServer(("", PORT), HealthHandler) as httpd:
            logging.info(f"Health check server running on port {PORT}")
            httpd.serve_forever()
    except Exception as e:
        logging.error(f"Port bind error: {e}")

def self_ping_loop():
    """Periodically pings the web server to prevent Render Free Tier spindown."""
    time.sleep(15)
    while True:
        try:
            url = RENDER_EXTERNAL_URL if RENDER_EXTERNAL_URL else f"http://127.0.0.1:{PORT}"
            req = urllib.request.Request(url, headers={'User-Agent': 'RenderKeepAlive/1.0'})
            with urllib.request.urlopen(req, timeout=10) as response:
                logging.info(f"Keep-alive self-ping successful: {response.status}")
        except Exception as e:
            logging.warning(f"Self-ping failed (harmless during boot): {e}")
        time.sleep(600)  # Ping every 10 minutes

def run_bot_script():
    """Executes run.py and ensures env vars are inherited."""
    env = os.environ.copy()
    token = env.get("BOT_TOKEN", "").strip()
    if not token:
        logging.error("⚠️ BOT_TOKEN IS MISSING OR EMPTY IN ENVIRONMENT VARIABLES!")
    else:
        logging.info(f"🔑 BOT_TOKEN detected (Length: {len(token)} characters)")
    
    subprocess.run(["python", "run.py"], env=env)

if __name__ == "__main__":
    # Start Web Server in a daemon thread
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Start Keep-Alive Ping loop in a daemon thread
    threading.Thread(target=self_ping_loop, daemon=True).start()

    # Start the actual Telegram Bot runner
    run_bot_script()