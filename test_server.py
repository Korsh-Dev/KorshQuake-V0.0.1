import unittest
import json
import urllib.request
import threading
import time
import os
import sys

# Import server components
import server

class TestKorshQuakeServer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = 8899  # Dedicated test port
        cls.server_thread = threading.Thread(target=server.run_server, args=(cls.port,), daemon=True)
        cls.server_thread.start()
        time.sleep(1.2) # Wait for server to bind

    def test_status_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("version", data)
        self.assertEqual(data["version"], "1.1.2")
        self.assertEqual(data["software_name"], "KorshQuake")
        self.assertIn("apk_url", data)
        self.assertIn("target_countries", data)
        self.assertEqual(set(data["target_countries"]), {"Panamá", "Venezuela", "España", "Argentina"})

    def test_quakes_strictly_target_countries(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes"
        req = urllib.request.urlopen(url, timeout=12)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        
        self.assertIn("features", data)
        self.assertIsInstance(data["features"], list)
        self.assertGreater(len(data["features"]), 0, "Debe haber al menos un evento en el feed")

        allowed_codes = {"PA", "VE", "ES", "AR"}
        allowed_names = {"Panamá", "Venezuela", "España", "Argentina"}

        # Verificar rigurosamente que el 100% de los sismos pertenezcan a los 4 países
        for f in data["features"]:
            props = f.get("properties", {})
            country_code = props.get("country_code")
            country_name = props.get("country_name")
            
            self.assertIn(country_code, allowed_codes, f"País no permitido detectado: {country_code} ({props.get('place')})")
            self.assertIn(country_name, allowed_names, f"Nombre de país no permitido: {country_name}")

        counts = data.get("metadata", {}).get("counts_by_country", {})
        self.assertTrue(any(counts[c] > 0 for c in allowed_codes), "Al menos un país debe tener eventos")

    def test_apk_download(self):
        url = f"http://127.0.0.1:{self.port}/KorshQuake.apk"
        req = urllib.request.urlopen(url, timeout=10)
        self.assertEqual(req.status, 200)
        content_type = req.headers.get("Content-Type")
        self.assertEqual(content_type, "application/vnd.android.package-archive")
        data = req.read()
        self.assertGreater(len(data), 50000, "El APK debe tener tamaño válido (> 50KB)")

    def test_pwa_manifest(self):
        url = f"http://127.0.0.1:{self.port}/manifest.json"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data["short_name"], "KorshQuake")
        self.assertEqual(data["display"], "standalone")

    def test_servers_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/servers"
        req = urllib.request.urlopen(url, timeout=10)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("servers", data)
        self.assertIsInstance(data["servers"], list)
        server_names = [s["name"] for s in data["servers"]]
        self.assertTrue(any("IGN" in n for n in server_names))
        self.assertTrue(any("FUNVISIS" in n for n in server_names))
        self.assertTrue(any("INPRES" in n for n in server_names))

    def test_logs_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/logs"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("logs", data)
        self.assertIsInstance(data["logs"], list)

    def test_stats_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/stats"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data["status"], "ONLINE")
        self.assertIn("counts_by_country", data)
        self.assertIn("total_events", data)
        self.assertIn("max_magnitude", data)
        self.assertIn("uptime_seconds", data)
        self.assertEqual(set(data["counts_by_country"].keys()), {"PA", "VE", "ES", "AR"})

    def test_health_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/health"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data["status"], "healthy")
        self.assertTrue(data["worker_thread_alive"])
        self.assertIn("memory_events_count", data)

    def test_quakes_query_parameters(self):
        # Filtro de país específico
        url = f"http://127.0.0.1:{self.port}/api/quakes?country=ES"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        for f in data["features"]:
            self.assertEqual(f["properties"]["country_code"], "ES")

        # Filtro de límite
        url_limit = f"http://127.0.0.1:{self.port}/api/quakes?limit=3"
        req_lim = urllib.request.urlopen(url_limit, timeout=5)
        data_lim = json.loads(req_lim.read().decode('utf-8'))
        self.assertLessEqual(len(data_lim["features"]), 3)

        # Filtro de magnitud mínima
        url_mag = f"http://127.0.0.1:{self.port}/api/quakes?min_mag=3.0"
        req_mag = urllib.request.urlopen(url_mag, timeout=5)
        data_mag = json.loads(req_mag.read().decode('utf-8'))
        for f in data_mag["features"]:
            self.assertGreaterEqual(float(f["properties"]["mag"]), 3.0)

    def test_latest_quake_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes/latest"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("found", data)
        if data["found"]:
            self.assertIn("event", data)
            self.assertIn("age_seconds", data)
            self.assertIn("is_live_alert", data)
            self.assertIn("alert_level", data)

    def test_gods_eye_view_route(self):
        url = f"http://127.0.0.1:{self.port}/gods-eye"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        content_type = req.headers.get("Content-Type")
        self.assertIn("text/html", content_type)
        html = req.read().decode('utf-8')
        self.assertIn("God's Eye View", html)

    def test_predict_endpoint_latest(self):
        url = f"http://127.0.0.1:{self.port}/api/predict"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("prediction_model", data)
        self.assertIn("velocities", data)
        self.assertEqual(data["velocities"]["vp_kms"], 7.8)
        self.assertEqual(data["velocities"]["vs_kms"], 4.1)
        self.assertIn("predictions", data)
        self.assertIsInstance(data["predictions"], list)

    def test_predict_custom_hypocenter(self):
        # Prueba con hipocentro simulado cerca de Caracas
        url = f"http://127.0.0.1:{self.port}/api/predict?lat=10.48&lon=-66.90&mag=5.5&depth=12.0"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data["mode"], "custom_hypocenter")
        self.assertGreater(len(data["predictions"]), 0)
        closest = data["predictions"][0]
        self.assertEqual(closest["city"], "Caracas")
        self.assertLess(closest["distance_km"], 20.0)
        self.assertIn("eta_s_sec", closest)
        self.assertIn("mmi_intensity", closest)
        self.assertIn("pga_gal", closest)

    def test_predictions_embedded_in_features(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertGreater(len(data["features"]), 0)
        for f in data["features"][:3]:
            props = f.get("properties", {})
            self.assertIn("predictions", props)
            self.assertIsInstance(props["predictions"], list)

    def test_live_events_sse_endpoint(self):
        import socket
        s = socket.create_connection(('127.0.0.1', self.port), timeout=5)
        req = (
            f"GET /api/events/live HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{self.port}\r\n"
            f"Accept: text/event-stream\r\n"
            f"Connection: close\r\n\r\n"
        )
        s.sendall(req.encode('utf-8'))
        resp = ""
        s.settimeout(2.5)
        for _ in range(5):
            try:
                chunk = s.recv(512).decode('utf-8', errors='ignore')
                if not chunk:
                    break
                resp += chunk
                if "event: ready" in resp:
                    break
            except Exception:
                break
        s.close()
        self.assertIn("200 OK", resp)
        self.assertIn("text/event-stream", resp)
        self.assertIn("event: ready", resp)

    def test_process_emsc_ws_message_injection(self):
        # Simular mensaje WebSocket de EMSC para Chiriquí (Panamá)
        ws_msg = json.dumps({
            "action": "create",
            "data": {
                "geometry": {
                    "type": "Point",
                    "coordinates": [-82.43, 8.42, -10.0]
                },
                "properties": {
                    "unid": "test_eew_panama_999",
                    "time": "2026-10-09T22:00:00Z",
                    "mag": 5.8,
                    "flynn_region": "Panama-Costa Rica Border",
                    "auth": "IGN",
                    "lat": 8.42,
                    "lon": -82.43,
                    "depth": 10.0
                }
            }
        })
        event = server.process_emsc_ws_message(ws_msg)
        self.assertIsNotNone(event)
        self.assertEqual(event["properties"]["country_code"], "PA")
        self.assertEqual(event["properties"]["mag"], 5.8)
        self.assertIn("predictions", event["properties"])
        self.assertGreater(len(event["properties"]["predictions"]), 0)

        # Verificar que el evento fue inyectado en el caché del servidor
        quakes = server.get_live_earthquakes()
        found_in_cache = any(f.get("id") == "emsc-live-test_eew_panama_999" for f in quakes.get("features", []))
        self.assertTrue(found_in_cache, "El sismo en vivo debe estar presente en el cache RAM del servidor")

if __name__ == '__main__':
    unittest.main()
