import unittest
import json
import urllib.request
import urllib.error
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

    def test_version_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/version"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data["version"], server.CURRENT_VERSION)
        self.assertEqual(data["version_code"], server.CURRENT_VERSION_CODE)
        self.assertTrue(data["ota_update_available"])
        self.assertIn("changelog", data)
        self.assertIsInstance(data["changelog"], list)
        self.assertGreater(len(data["changelog"]), 0)

    def test_status_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/status"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("version", data)
        self.assertEqual(data["version"], server.CURRENT_VERSION)
        self.assertEqual(data["software_name"], "KorshQuake")
        self.assertIn("apk_url", data)
        self.assertIn("target_countries", data)
        self.assertEqual(set(data["target_countries"]), {"Panamá", "Venezuela", "España", "Argentina", "Honduras"})

    def test_quakes_strictly_target_countries(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes"
        req = urllib.request.urlopen(url, timeout=12)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        
        self.assertIn("features", data)
        self.assertIsInstance(data["features"], list)
        self.assertGreater(len(data["features"]), 0, "Debe haber al menos un evento en el feed")

        allowed_codes = {"PA", "VE", "ES", "AR", "HN"}
        allowed_names = {"Panamá", "Venezuela", "España", "Argentina", "Honduras"}

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
        self.assertEqual(set(data["counts_by_country"].keys()), {"PA", "VE", "ES", "AR", "HN"})

    def test_health_endpoint(self):
        for ep in ["/api/health", "/health"]:
            url = f"http://127.0.0.1:{self.port}{ep}"
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


    def test_mesh_node_registration_and_list(self):
        # 1. Registrar un nodo móvil con GPS activo vía POST /api/nodes/ping
        url_ping = f"http://127.0.0.1:{self.port}/api/nodes/ping"
        payload = json.dumps({
            "node_id": "test-phone-caracas-01",
            "lat": 10.4806,
            "lon": -66.9036,
            "accuracy": 8.5,
            "pga": 0.04,
            "sta_lta": 1.1,
            "noise_floor": 0.02,
            "platform": "apk",
            "device": "Samsung Galaxy S23",
            "gps_enabled": True,
            "location_mode": "gps_fine"
        }).encode("utf-8")

        req = urllib.request.Request(url_ping, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertEqual(data["node_id"], "test-phone-caracas-01")
        self.assertEqual(data["country"], "VE")
        self.assertEqual(data["status"], "active_node")
        self.assertTrue(data["gps_enabled"])
        self.assertEqual(data["accuracy_m"], 8.5)
        self.assertGreaterEqual(data["total_network_nodes"], 1)

        # 2. Verificar que aparece listado en GET /api/nodes/list con metadatos GPS
        url_list = f"http://127.0.0.1:{self.port}/api/nodes/list"
        req_list = urllib.request.urlopen(url_list, timeout=5)
        self.assertEqual(req_list.status, 200)
        list_data = json.loads(req_list.read().decode("utf-8"))
        self.assertIn("nodes", list_data)
        node_item = next((n for n in list_data["nodes"] if n["node_id"] == "test-phone-caracas-01"), None)
        self.assertIsNotNone(node_item, "El nodo registrado debe aparecer en la lista de nodos activos")
        self.assertTrue(node_item["gps_enabled"])

        # 3. Registrar un nodo sin GPS activo y verificar que exige ubicación
        payload_nogps = json.dumps({
            "node_id": "test-phone-nogps",
            "lat": 0.0,
            "lon": 0.0,
            "accuracy": 999.0,
            "gps_enabled": False,
            "location_mode": "denied"
        }).encode("utf-8")
        req_nogps = urllib.request.Request(url_ping, data=payload_nogps, headers={"Content-Type": "application/json"})
        resp_nogps = urllib.request.urlopen(req_nogps, timeout=5)
        data_nogps = json.loads(resp_nogps.read().decode("utf-8"))
        self.assertEqual(data_nogps["status"], "location_required")
        self.assertFalse(data_nogps["gps_enabled"])

        # 4. Registrar una computadora como Estación Centinela de Apoyo
        payload_pc = json.dumps({
            "node_id": "test-desktop-madrid-01",
            "lat": 40.4168,
            "lon": -3.7038,
            "accuracy": 25.0,
            "platform": "desktop",
            "device": "Windows PC (Workstation Sentinel)",
            "node_type": "desktop_pc"
        }).encode("utf-8")
        req_pc = urllib.request.Request(url_ping, data=payload_pc, headers={"Content-Type": "application/json"})
        resp_pc = urllib.request.urlopen(req_pc, timeout=5)
        data_pc = json.loads(resp_pc.read().decode("utf-8"))
        self.assertEqual(data_pc["node_type"], "desktop_pc")
        self.assertEqual(data_pc["role"], "Estación Centinela Fija")
        self.assertEqual(data_pc["status"], "active_node")
        self.assertGreaterEqual(data_pc["desktop_nodes_count"], 1)

    def test_mesh_single_node_trigger_avoids_false_alarm(self):
        # Un solo telfono movindose (sacudida accidental) NO debe disparar alerta de sismo
        url_trigger = f"http://127.0.0.1:{self.port}/api/nodes/trigger"
        payload = json.dumps({
            "node_id": "isolated-phone-99",
            "lat": 8.9824,
            "lon": -79.5199, # Panam
            "pga": 28.0,
            "sta_lta": 5.2,
            "device": "Pixel 8"
        }).encode("utf-8")

        req = urllib.request.Request(url_trigger, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertFalse(data["cluster_detected"], "Un solo telfono no debe generar alerta ssmica (debe evitar falsos positivos)")
        self.assertEqual(data["nodes_count"], 1)

    def test_mesh_multi_node_coincidence_confirms_earthquake(self):
        # Dos telfonos cercanos (< 50 km) disparando en la misma ventana temporal confirman el sismo
        url_trigger = f"http://127.0.0.1:{self.port}/api/nodes/trigger"

        # Telfono A en Caracas Este
        payload_a = json.dumps({
            "node_id": "coincidence-phone-alpha",
            "lat": 10.4900,
            "lon": -66.8500,
            "pga": 45.2,
            "sta_lta": 5.8,
            "device": "Galaxy S24"
        }).encode("utf-8")
        req_a = urllib.request.Request(url_trigger, data=payload_a, headers={"Content-Type": "application/json"})
        resp_a = urllib.request.urlopen(req_a, timeout=5)
        self.assertEqual(resp_a.status, 200)

        # Telfono B en Caracas Oeste (~12 km de distancia) dentro de los siguientes 2 segundos
        payload_b = json.dumps({
            "node_id": "coincidence-phone-beta",
            "lat": 10.5100,
            "lon": -66.9500,
            "pga": 48.6,
            "sta_lta": 6.1,
            "device": "Xiaomi 13"
        }).encode("utf-8")
        req_b = urllib.request.Request(url_trigger, data=payload_b, headers={"Content-Type": "application/json"})
        resp_b = urllib.request.urlopen(req_b, timeout=5)
        self.assertEqual(resp_b.status, 200)
        data_b = json.loads(resp_b.read().decode("utf-8"))

        self.assertTrue(data_b["cluster_detected"], "Mltiples telfonos cercanos deben confirmar el sismo de red")
        self.assertGreaterEqual(data_b["nodes_count"], 2)
        self.assertIn("estimated_magnitude", data_b)
        self.assertGreaterEqual(data_b["estimated_magnitude"], 3.0)
        self.assertTrue(data_b["eew_issued"], "Debe emitirse la alerta ssmica temprana (EEW)")

    def test_mesh_test_cluster_and_stats(self):
        # Probar endpoint de simulacin de cluster
        url_test = f"http://127.0.0.1:{self.port}/api/nodes/test_cluster"
        payload = json.dumps({
            "lat": 40.4168,
            "lon": -3.7038, # Madrid
            "pga": 35.0,
            "nodes_count": 3
        }).encode("utf-8")

        req = urllib.request.Request(url_test, data=payload, headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=5)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode("utf-8"))
        self.assertTrue(data["cluster_detected"])

        # Verificar estadsticas de nodos
        url_stats = f"http://127.0.0.1:{self.port}/api/nodes/stats"
        resp_stats = urllib.request.urlopen(url_stats, timeout=5)
        self.assertEqual(resp_stats.status, 200)
        stats = json.loads(resp_stats.read().decode("utf-8"))
        self.assertIn("service", stats)
        self.assertGreaterEqual(stats["confirmed_clusters_count"], 1)

        # Verificar que el cluster confirmado se encuentre en el feed de sismos (/api/quakes)
        url_quakes = f"http://127.0.0.1:{self.port}/api/quakes"
        resp_quakes = urllib.request.urlopen(url_quakes, timeout=5)
        self.assertEqual(resp_quakes.status, 200)
        quakes_data = json.loads(resp_quakes.read().decode("utf-8"))
        features = quakes_data.get("features", [])
        cluster_feature = next((f for f in features if f.get("id") == data["cluster_id"]), None)
        self.assertIsNotNone(cluster_feature)
        self.assertEqual(cluster_feature["properties"]["status"], "CROWDSOURCED_CONFIRMED")

    def test_admin_portal_and_cluster_purge(self):
        # 1. Probar acceso a la interfaz web de admin /admin
        url_admin = f"http://127.0.0.1:{self.port}/admin"
        resp_admin = urllib.request.urlopen(url_admin, timeout=5)
        self.assertEqual(resp_admin.status, 200)
        self.assertIn("text/html", resp_admin.headers.get("Content-Type", ""))
        html_body = resp_admin.read().decode("utf-8")
        self.assertIn("Admin Console", html_body)

        # 2. Probar API de listado de nodos para administradores /api/admin/nodes
        url_nodes = f"http://127.0.0.1:{self.port}/api/admin/nodes"
        resp_nodes = urllib.request.urlopen(url_nodes, timeout=5)
        self.assertEqual(resp_nodes.status, 200)
        nodes_data = json.loads(resp_nodes.read().decode("utf-8"))
        self.assertIn("nodes", nodes_data)
        self.assertIn("total", nodes_data)

        # 3. Probar purga administrativa de clusters de prueba /api/admin/clear_test_clusters
        url_clear = f"http://127.0.0.1:{self.port}/api/admin/clear_test_clusters"
        req_clear = urllib.request.Request(url_clear, data=b"{}", headers={"Content-Type": "application/json"})
        resp_clear = urllib.request.urlopen(req_clear, timeout=5)
        self.assertEqual(resp_clear.status, 200)
        clear_res = json.loads(resp_clear.read().decode("utf-8"))
        self.assertTrue(clear_res.get("success"))
        self.assertGreaterEqual(clear_res.get("cleared_count", 0), 1)


    def test_real_felt_reports_flow(self):
        quake_id = 'test-quake-123'
        # 1. GET initial report count
        url_get = f'http://127.0.0.1:{self.port}/api/quakes/{quake_id}/report'
        req = urllib.request.urlopen(url_get, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        initial_count = data.get('felt_reports', 0)
        
        # 2. POST report
        url_post = f'http://127.0.0.1:{self.port}/api/quakes/report'
        post_data = json.dumps({'quake_id': quake_id, 'lat': 8.5, 'lon': -80.2}).encode('utf-8')
        req2 = urllib.request.Request(url_post, data=post_data, headers={'Content-Type': 'application/json'})
        resp2 = urllib.request.urlopen(req2, timeout=5)
        self.assertEqual(resp2.status, 200)
        res_data = json.loads(resp2.read().decode('utf-8'))
        self.assertTrue(res_data.get('success'))
        self.assertGreaterEqual(res_data.get('felt_reports', 0), initial_count)


    def test_shakemap_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes/shakemap?quake_id=test-quake-123"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("quake_id", data)
        self.assertIn("total_reports", data)
        self.assertIn("points", data)
        self.assertIsInstance(data["points"], list)

    def test_history_endpoint(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes/history?limit=10"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        data = json.loads(req.read().decode('utf-8'))
        self.assertIn("count", data)
        self.assertIn("features", data)
        self.assertIsInstance(data["features"], list)

    def test_export_geojson(self):
        url = f"http://127.0.0.1:{self.port}/api/export/geojson"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        self.assertIn("application/geo+json", req.headers.get("Content-Type", ""))
        self.assertIn("korshquake_catalog.geojson", req.headers.get("Content-Disposition", ""))
        data = json.loads(req.read().decode('utf-8'))
        self.assertEqual(data.get("type"), "FeatureCollection")

    def test_export_csv(self):
        url = f"http://127.0.0.1:{self.port}/api/export/csv"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        self.assertIn("text/csv", req.headers.get("Content-Type", ""))
        csv_text = req.read().decode('utf-8')
        self.assertTrue(csv_text.startswith("id,time_utc"))

    def test_export_quakeml(self):
        url = f"http://127.0.0.1:{self.port}/api/export/quakeml"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        self.assertIn("application/xml", req.headers.get("Content-Type", ""))
        xml_text = req.read().decode('utf-8')
        self.assertIn("<q:quakeml", xml_text)

    def test_event_opengraph_route(self):
        url = f"http://127.0.0.1:{self.port}/event/test-quake-123"
        req = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(req.status, 200)
        html = req.read().decode('utf-8')
        self.assertIn("og:title", html)
        self.assertIn("og:description", html)
        self.assertIn("og:image", html)

    def test_push_endpoints(self):
        # 1. GET public key
        url_pk = f"http://127.0.0.1:{self.port}/api/push/public_key"
        req_pk = urllib.request.urlopen(url_pk, timeout=5)
        self.assertEqual(req_pk.status, 200)
        data_pk = json.loads(req_pk.read().decode('utf-8'))
        self.assertIn("public_key", data_pk)

        # 2. POST subscribe
        url_sub = f"http://127.0.0.1:{self.port}/api/push/subscribe"
        sub_payload = json.dumps({
            "endpoint": "https://fcm.googleapis.com/fcm/send/test-sub-token",
            "keys": {"p256dh": "test-key-p256dh", "auth": "test-auth-token"},
            "min_mag": 4.5,
            "country": "VE"
        }).encode('utf-8')
        req_sub = urllib.request.Request(url_sub, data=sub_payload, headers={'Content-Type': 'application/json'}, method='POST')
        resp_sub = urllib.request.urlopen(req_sub, timeout=5)
        self.assertEqual(resp_sub.status, 200)
        sub_res = json.loads(resp_sub.read().decode('utf-8'))
        self.assertTrue(sub_res.get("success"))

        # 3. POST test
        url_test = f"http://127.0.0.1:{self.port}/api/push/test"
        req_test = urllib.request.Request(url_test, data=b"{}", headers={'Content-Type': 'application/json'}, method='POST')
        resp_test = urllib.request.urlopen(req_test, timeout=5)
        self.assertEqual(resp_test.status, 200)
        test_res = json.loads(resp_test.read().decode('utf-8'))
        self.assertTrue(test_res.get("success"))

    def test_focal_mechanism_embedded(self):
        fm = server.compute_focal_mechanism(10.48, -66.90, 12.0, 5.5)
        self.assertIn("strike", fm)
        self.assertIn("dip", fm)
        self.assertIn("rake", fm)
        self.assertIn("beachball_svg", fm)
        self.assertIn("<svg", fm["beachball_svg"])

    # --- Regresión: auditoría de robustez (inputs malformados no deben producir 500) ---

    def _post_json(self, path, payload, expect_status=200):
        url = f"http://127.0.0.1:{self.port}{path}"
        data = json.dumps(payload).encode('utf-8') if not isinstance(payload, bytes) else payload
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json'}, method='POST')
        try:
            resp = urllib.request.urlopen(req, timeout=5)
            status, body = resp.status, resp.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            status, body = e.code, e.read().decode('utf-8')
        self.assertEqual(status, expect_status, f"{path} -> {status}: {body[:200]}")
        return body

    def test_telemetry_malformed_numbers_no_crash(self):
        body = self._post_json("/api/nodes/ping", {"node_id": "audit-node", "lat": "abc", "lon": None, "pga": "NaN-ish"})
        res = json.loads(body)
        self.assertIn("node_id", res)

    def test_trigger_malformed_numbers_no_crash(self):
        body = self._post_json("/api/nodes/trigger", {"node_id": "audit-node", "lat": [1], "pga": {"x": 1}})
        res = json.loads(body)
        self.assertIn("cluster_detected", res)

    def test_report_missing_quake_id_returns_400_not_500(self):
        # POST /api/quakes/report sin quake_id: antes reventaba con IndexError (500)
        self._post_json("/api/quakes/report", {}, expect_status=400)

    def test_push_subscribe_bad_min_mag_no_crash(self):
        body = self._post_json("/api/push/subscribe", {
            "endpoint": "https://fcm.googleapis.com/fcm/send/audit-token",
            "keys": {"p256dh": "k", "auth": "a"},
            "min_mag": "no-es-numero"
        })
        self.assertTrue(json.loads(body).get("success"))

    def test_history_bad_query_params_no_crash(self):
        url = f"http://127.0.0.1:{self.port}/api/quakes/history?limit=abc&offset=xyz&min_mag=foo&max_mag=bar"
        resp = urllib.request.urlopen(url, timeout=5)
        self.assertEqual(resp.status, 200)
        data = json.loads(resp.read().decode('utf-8'))
        self.assertIn("features", data)

    def test_csv_export_valid_quoting(self):
        url = f"http://127.0.0.1:{self.port}/api/export/csv"
        resp = urllib.request.urlopen(url, timeout=10)
        self.assertEqual(resp.status, 200)
        text = resp.read().decode('utf-8')
        lines = text.strip().split("\n")
        self.assertEqual(lines[0].split(",")[0], "id")
        import csv as csv_mod
        import io
        rows = list(csv_mod.reader(io.StringIO(text)))
        self.assertEqual(len(rows[0]), 12)
        for row in rows[1:]:
            self.assertEqual(len(row), 12, f"fila CSV con columnas rotas: {row}")

    def test_vapid_public_key_is_real_p256(self):
        import base64
        key = server.VAPID_PUBLIC_KEY
        self.assertEqual(len(key), 87, "clave VAPID debe ser 65 bytes en base64url sin padding")
        raw = base64.urlsafe_b64decode(key + "=")
        self.assertEqual(len(raw), 65)
        self.assertEqual(raw[0], 0x04, "debe ser punto EC no comprimido")

    def test_admin_open_when_no_token(self):
        # Comportamiento histórico: sin ADMIN_TOKEN, /admin responde
        resp = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/admin", timeout=5)
        self.assertEqual(resp.status, 200)

    def test_admin_gate_when_token_configured(self):
        original = server.ADMIN_TOKEN
        try:
            server.ADMIN_TOKEN = "audit-secret-123"
            # Sin token -> 401 en API admin
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/admin/nodes", timeout=5)
            self.assertEqual(ctx.exception.code, 401)
            # Con header correcto -> 200
            req = urllib.request.Request(
                f"http://127.0.0.1:{self.port}/api/admin/nodes",
                headers={"X-Admin-Token": "audit-secret-123"})
            resp = urllib.request.urlopen(req, timeout=5)
            self.assertEqual(resp.status, 200)
            # /admin HTML sin token -> 401
            with self.assertRaises(urllib.error.HTTPError) as ctx2:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/admin", timeout=5)
            self.assertEqual(ctx2.exception.code, 401)
            # Rutas públicas no afectadas
            resp_pub = urllib.request.urlopen(f"http://127.0.0.1:{self.port}/api/nodes/list", timeout=5)
            self.assertEqual(resp_pub.status, 200)
        finally:
            server.ADMIN_TOKEN = original

if __name__ == '__main__':
    unittest.main()
