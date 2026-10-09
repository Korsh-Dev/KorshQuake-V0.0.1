import http.server
import subprocess
import threading
import json

PORT = 8089

class WebhookHandler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length)
        
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
        self.wfile.write(json.dumps({"service": "korshquake-webhook", "status": "online"}).encode('utf-8'))

    def log_message(self, format, *args):
        pass

if __name__ == '__main__':
    server = http.server.ThreadingHTTPServer(('127.0.0.1', PORT), WebhookHandler)
    server.serve_forever()
