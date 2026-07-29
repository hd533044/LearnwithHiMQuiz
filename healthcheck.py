import http.server
import socketserver
import os
import subprocess
import threading

# Start a lightweight web server on the port Render provides
PORT = int(os.environ.get("PORT", 10000))
Handler = http.server.SimpleHTTPRequestHandler

try:
    httpd = socketserver.TCPServer(("", PORT), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    print(f"Health check server running on port {PORT}")
except Exception as e:
    print(f"Port bind error: {e}")

# Run your actual Telegram bot script
subprocess.run(["python", "run.py"])