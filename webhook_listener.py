import http.server
import subprocess
import threading
import json
import hmac
import hashlib
import os

PORT = 8089
WEBHOOK_SECRET = os.environ.get("GITHUB_WEBHOOK_SECRET", "")


class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)

        # Verificación de firma X-Hub-Signature-256 (solo si GITHUB_WEBHOOK_SECRET está configurado)
        if WEBHOOK_SECRET:
            signature = self.headers.get('X-Hub-Signature-256', '')
            expected = "sha256=" + hmac.new(WEBHOOK_SECRET.encode('utf-8'), post_data, hashlib.sha256).hexdigest()
            if not signature or not hmac.compare_digest(signature, expected):
                self.send_response(403)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "forbidden", "message": "Invalid webhook signature"}).encode('utf-8'))
                return

        # Disparar actualizacion en hilo independiente
        def trigger_update():
            try:
                subprocess.run(["/opt/korshquake/auto-update.sh"], check=True)
            except Exception as e:
                print(f"[ERROR] Error al ejecutar auto-update: {e}")

        threading.Thread(target=trigger_update, daemon=True).start()

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"status": "success", "message": "KorshQuake update triggered"}).encode('utf-8'))

    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps({"service": "korshquake-webhook", "status": "online", "signature_check": bool(WEBHOOK_SECRET)}).encode('utf-8'))

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), WebhookHandler)
    server.serve_forever()
