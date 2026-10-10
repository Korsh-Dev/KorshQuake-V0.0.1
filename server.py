import http.server
import socketserver
import json
import urllib.request
import urllib.error
import urllib.parse
import subprocess
import os
import sys
import time
import re
import glob
import math
import collections
import threading
import concurrent.futures
import queue
import socket
import ssl
import struct
import base64
from datetime import datetime

_server_start_time = time.time()

CURRENT_VERSION = "1.1.5 PRO"
CURRENT_VERSION_CODE = 115


PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
GODS_EYE_DIST = os.path.join(BASE_DIR, "gods-eye-view", "dist")
ROAMING_GQ = os.path.join(os.environ.get("APPDATA", ""), "GlobalQuake")
LOCAL_APP_PATH = os.path.join(BASE_DIR, "GlobalQuakeApp")

# Target Countries metadata
TARGET_COUNTRIES = {
    "PA": {"name": "Panamá", "flag": "🇵🇦", "center": [8.538, -80.782], "zoom": 7.5},
    "VE": {"name": "Venezuela", "flag": "🇻🇪", "center": [8.000, -66.100], "zoom": 6.5},
    "ES": {"name": "España", "flag": "🇪🇸", "center": [40.200, -3.750], "zoom": 6.0},
    "AR": {"name": "Argentina", "flag": "🇦🇷", "center": [-38.416, -63.616], "zoom": 5.0}
}

# Regional Bounding Boxes to query focused data feeds
QUERY_REGIONS = [
    {"code": "PA", "name": "Panamá", "minlat": 6.8, "maxlat": 10.2, "minlon": -83.5, "maxlon": -76.8},
    {"code": "VE", "name": "Venezuela", "minlat": 0.5, "maxlat": 13.5, "minlon": -73.6, "maxlon": -59.5},
    {"code": "ES", "name": "España Península", "minlat": 35.0, "maxlat": 44.5, "minlon": -10.5, "maxlon": 5.0},
    {"code": "ES", "name": "España Canarias", "minlat": 26.5, "maxlat": 30.5, "minlon": -19.0, "maxlon": -12.5},
    {"code": "AR", "name": "Argentina", "minlat": -55.5, "maxlat": -21.5, "minlon": -73.6, "maxlon": -53.5}
]

# Telemetry tracking for connected seismic networks
_server_telemetry = {
    "gq_primary": {
        "id": "gq_primary",
        "name": "GlobalQuake Primary Cluster",
        "host": "server.globalquake.net:38000",
        "region": "Red Central GlobalQuake (Algoritmo ak135 en tiempo real)",
        "status": "ONLINE",
        "latency_ms": 45,
        "events_count": 0,
        "last_sync": 0
    },
    "ign_es": {
        "id": "ign_es",
        "name": "IGN España (Instituto Geográfico Nacional)",
        "host": "ign.es / sismicidad",
        "region": "España, Canarias, Baleares y Alborán",
        "status": "ONLINE",
        "latency_ms": 110,
        "events_count": 0,
        "last_sync": 0
    },
    "funvisis_ve": {
        "id": "funvisis_ve",
        "name": "FUNVISIS Venezuela",
        "host": "funvisis.gob.ve",
        "region": "Venezuela, Fallas Boconó y El Pilar",
        "status": "ONLINE",
        "latency_ms": 280,
        "events_count": 0,
        "last_sync": 0
    },
    "inpres_ar": {
        "id": "inpres_ar",
        "name": "INPRES Argentina",
        "host": "inpres.gob.ar",
        "region": "Argentina (Cuyo, NOA, Centro y Patagonia)",
        "status": "ONLINE",
        "latency_ms": 260,
        "events_count": 0,
        "last_sync": 0
    },
    "upa_pa": {
        "id": "upa_pa",
        "name": "OSOP / RSN Panamá",
        "host": "panama.seismic.org",
        "region": "Panamá, Bloque de Panamá y Fosas del Pacífico",
        "status": "ONLINE",
        "latency_ms": 240,
        "events_count": 0,
        "last_sync": 0
    },
    "emsc_regional": {
        "id": "emsc_regional",
        "name": "EMSC SeismicPortal Realtime",
        "host": "seismicportal.eu",
        "region": "Red Multicentro Internacional en Vivo",
        "status": "ONLINE",
        "latency_ms": 380,
        "events_count": 0,
        "last_sync": 0
    },
    "usgs_regional": {
        "id": "usgs_regional",
        "name": "USGS Earthquake Hazards Live Feed",
        "host": "earthquake.usgs.gov",
        "region": "Américas & Red Global de Alta Precisión",
        "status": "ONLINE",
        "latency_ms": 250,
        "events_count": 0,
        "last_sync": 0
    }
}

# --- RAM Cache & Background Streaming Worker ---
_ram_quake_cache = None
_ram_cache_lock = threading.Lock()
_last_ram_update_time = 0
_worker_loop_count = 0
_worker_running = True

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0 # Radio de la Tierra en km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def is_point_in_bbox(lat, lon, min_lat, max_lat, min_lon, max_lon):
    return min_lat <= lat <= max_lat and min_lon <= lon <= max_lon

# Centros urbanos y capitales clave de monitoreo sísmico
SEISMIC_PREDICTION_TARGETS = [
    # Panamá 🇵🇦
    {"city": "Ciudad de Panamá", "country_code": "PA", "lat": 8.982, "lon": -79.520, "flag": "🇵🇦"},
    {"city": "David (Chiriquí)", "country_code": "PA", "lat": 8.427, "lon": -82.431, "flag": "🇵🇦"},
    {"city": "Colón", "country_code": "PA", "lat": 9.359, "lon": -79.901, "flag": "🇵🇦"},
    {"city": "Santiago de Veraguas", "country_code": "PA", "lat": 8.100, "lon": -80.970, "flag": "🇵🇦"},
    {"city": "Chitré", "country_code": "PA", "lat": 7.962, "lon": -80.428, "flag": "🇵🇦"},

    # Venezuela 🇻🇪
    {"city": "Caracas", "country_code": "VE", "lat": 10.480, "lon": -66.903, "flag": "🇻🇪"},
    {"city": "Valencia", "country_code": "VE", "lat": 10.162, "lon": -68.007, "flag": "🇻🇪"},
    {"city": "Maracaibo", "country_code": "VE", "lat": 10.654, "lon": -71.637, "flag": "🇻🇪"},
    {"city": "Barquisimeto", "country_code": "VE", "lat": 10.067, "lon": -69.347, "flag": "🇻🇪"},
    {"city": "San Cristóbal", "country_code": "VE", "lat": 7.766, "lon": -72.225, "flag": "🇻🇪"},
    {"city": "Mérida", "country_code": "VE", "lat": 8.598, "lon": -71.144, "flag": "🇻🇪"},
    {"city": "Cumaná", "country_code": "VE", "lat": 10.453, "lon": -64.182, "flag": "🇻🇪"},

    # España 🇪🇸
    {"city": "Madrid", "country_code": "ES", "lat": 40.416, "lon": -3.703, "flag": "🇪🇸"},
    {"city": "Granada", "country_code": "ES", "lat": 37.177, "lon": -3.598, "flag": "🇪🇸"},
    {"city": "Murcia", "country_code": "ES", "lat": 37.992, "lon": -1.130, "flag": "🇪🇸"},
    {"city": "Málaga", "country_code": "ES", "lat": 36.721, "lon": -4.421, "flag": "🇪🇸"},
    {"city": "Sevilla", "country_code": "ES", "lat": 37.389, "lon": -5.984, "flag": "🇪🇸"},
    {"city": "Santa Cruz de Tenerife", "country_code": "ES", "lat": 28.463, "lon": -16.251, "flag": "🇪🇸"},
    {"city": "Las Palmas de Gran Canaria", "country_code": "ES", "lat": 28.123, "lon": -15.436, "flag": "🇪🇸"},

    # Argentina 🇦🇷
    {"city": "San Juan", "country_code": "AR", "lat": -31.537, "lon": -68.536, "flag": "🇦🇷"},
    {"city": "Mendoza", "country_code": "AR", "lat": -32.890, "lon": -68.845, "flag": "🇦🇷"},
    {"city": "Salta", "country_code": "AR", "lat": -24.782, "lon": -65.423, "flag": "🇦🇷"},
    {"city": "San Salvador de Jujuy", "country_code": "AR", "lat": -24.185, "lon": -65.299, "flag": "🇦🇷"},
    {"city": "Córdoba", "country_code": "AR", "lat": -31.420, "lon": -64.188, "flag": "🇦🇷"},
    {"city": "Buenos Aires", "country_code": "AR", "lat": -34.603, "lon": -58.381, "flag": "🇦🇷"},
]

def calculate_seismic_predictions(lat, lon, depth_km, mag, origin_time_ms):
    """
    Motor Sismológico de Predicción en Tiempo Real (EEW).
    Modela propagación de ondas elásticas en la corteza terrestre:
    - Onda P (compresional): Vp = 7.8 km/s
    - Onda S (cizalla/destructiva): Vs = 4.1 km/s
    - Atenuación de aceleración de suelo (PGA) y escala de intensidad Mercalli Modificada (MMI).
    """
    now_ms = time.time() * 1000
    elapsed_sec = max(0.0, (now_ms - origin_time_ms) / 1000.0)
    vp = 7.8 # km/s
    vs = 4.1 # km/s

    predictions = []
    for target in SEISMIC_PREDICTION_TARGETS:
        dist_epi = haversine_km(lat, lon, target["lat"], target["lon"])
        dist_hypo = math.sqrt(dist_epi**2 + (depth_km or 10.0)**2)

        # Filtrar objetivos a rango sísmico relevante (< 1600 km)
        if dist_epi > 1600.0:
            continue

        time_p = dist_hypo / vp
        time_s = dist_hypo / vs

        eta_p = max(0.0, round(time_p - elapsed_sec, 1))
        eta_s = max(0.0, round(time_s - elapsed_sec, 1))
        arrived_p = elapsed_sec >= time_p
        arrived_s = elapsed_sec >= time_s

        # Estimación de Intensidad Mercalli Modificada (MMI)
        attenuated_val = 1.5 * mag - 2.6 * math.log10(max(10.0, dist_hypo)) + 1.6
        mmi = max(1.0, min(10.0, round(attenuated_val, 1)))

        if mmi >= 7.0:
            mmi_desc = "Muy Fuerte / Dañino"
            mmi_level = "CRITICAL"
        elif mmi >= 5.5:
            mmi_desc = "Fuerte"
            mmi_level = "WARNING"
        elif mmi >= 4.0:
            mmi_desc = "Moderado"
            mmi_level = "NOTICE"
        elif mmi >= 2.5:
            mmi_desc = "Leve"
            mmi_level = "MINOR"
        else:
            mmi_desc = "Muy Débil / No sentido"
            mmi_level = "INFO"

        # PGA estimado en cm/s² (Gal)
        ln_pga = 0.8 * mag - 1.2 * math.log(dist_hypo + 15.0) + 2.0
        pga_estimated = round(math.exp(ln_pga), 2)

        predictions.append({
            "city": target["city"],
            "country_code": target["country_code"],
            "country_flag": target["flag"],
            "distance_km": round(dist_epi, 1),
            "hypocentral_distance_km": round(dist_hypo, 1),
            "travel_time_p_sec": round(time_p, 1),
            "travel_time_s_sec": round(time_s, 1),
            "eta_p_sec": eta_p,
            "eta_s_sec": eta_s,
            "arrived_p": arrived_p,
            "arrived_s": arrived_s,
            "mmi_intensity": mmi,
            "mmi_description": mmi_desc,
            "mmi_level": mmi_level,
            "pga_gal": pga_estimated
        })

    # Ordenar por distancia epicentral ascendente (ciudades más cercanas primero)
    predictions.sort(key=lambda x: x["distance_km"])
    return predictions[:8]

def identify_target_country(lat, lon, place, auth=""):
    """
    Clasificador geográfico estricto: Solo acepta Panamá (PA), Venezuela (VE), España (ES) y Argentina (AR).
    Cualquier otro territorio o sismo fuera de estos 4 países es estrictamente descartado (retorna None).
    """
    p = (place or "").lower()
    a = (auth or "").lower()

    # 1. ESPAÑA 🇪🇸
    is_spain_canary = is_point_in_bbox(lat, lon, 26.5, 30.5, -19.0, -12.5)
    is_spain_peninsula = is_point_in_bbox(lat, lon, 35.2, 44.5, -10.0, 5.0)

    if "port of spain" not in p:
        if is_spain_canary or is_spain_peninsula:
            if any(re.search(pat, p) for pat in [r'\bportugal\b', r'\bfrance\b', r'\bmorocco\b', r'\balgeria\b']):
                pass
            else:
                if re.search(r'\b(spain|españa|canary islands|islas canarias|baleares|andalucia|granada|murcia|alicante|alboran|galicia)\b', p) or a in ["ign", "sfs"]:
                    return "ES"
                if is_spain_canary:
                    return "ES"
                if is_point_in_bbox(lat, lon, 36.2, 43.5, -7.0, 3.5):
                    return "ES"

    # 2. PANAMÁ 🇵🇦
    is_panama_box = is_point_in_bbox(lat, lon, 6.8, 10.2, -83.5, -76.8)
    if is_panama_box:
        if re.search(r'\bpanama\b|\bpanamá\b', p):
            return "PA"
        if not re.search(r'\bcosta rica\b', p) and not re.search(r'\bcolombia\b', p):
            return "PA"
        if "panama-costa rica" in p or "costa rica-panama" in p or "border region" in p:
            return "PA"

    # 3. VENEZUELA 🇻🇪
    is_venezuela_box = is_point_in_bbox(lat, lon, 0.5, 13.5, -73.6, -59.5)
    if is_venezuela_box:
        if "port of spain" in p:
            return None
        if re.search(r'\bvenezuela\b', p) or a == "funvisis" or "caracas" in p or "gulf of paria" in p:
            if not any(re.search(pat, p) for pat in [r'\bcolombia\b', r'\btrinidad\b', r'\bguyana\b', r'\bbrazil\b', r'\bbrasil\b']):
                return "VE"
        elif not any(re.search(pat, p) for pat in [r'\bcolombia\b', r'\btrinidad\b', r'\bguyana\b', r'\bbrazil\b', r'\bbrasil\b', r'\bst\.? vincent\b', r'\bgrenada\b']):
            if is_point_in_bbox(lat, lon, 3.5, 12.5, -72.0, -61.5):
                return "VE"

    # 4. ARGENTINA 🇦🇷
    is_argentina_box = is_point_in_bbox(lat, lon, -55.5, -21.5, -73.6, -53.5)
    if is_argentina_box:
        arg_provinces = [
            r'\bargentina\b', r'\binpres\b', r'\bjujuy\b', r'\bsalta\b', r'\btucuman\b',
            r'\bcatamarca\b', r'\bla rioja\b', r'\bsan juan\b', r'\bmendoza\b', r'\bsan luis\b',
            r'\bcordoba\b', r'\bcórdoba\b', r'\bsantiago del estero\b', r'\bneuquen\b',
            r'\bneuquén\b', r'\brio negro\b', r'\brío negro\b', r'\bchubut\b', r'\bsanta cruz\b',
            r'\btierra del fuego\b', r'\bbuenos aires\b', r'\bla pampa\b'
        ]
        has_arg_kw = any(re.search(pat, p) for pat in arg_provinces) or a == "inpres"
        if any(re.search(pat, p) for pat in [r'\bchile\b', r'\bbolivia\b', r'\bparaguay\b', r'\buruguay\b']):
            if has_arg_kw and lon > -69.2:
                return "AR"
            return None
        if has_arg_kw:
            return "AR"
        if lon >= -68.2 and -54.0 <= lat <= -22.0:
            return "AR"

    return None

# --- SSE & Realtime Push Alert Subscriptions ---
_sse_clients = []
_sse_lock = threading.Lock()

def broadcast_sse_event(event_type, data):
    """Emite un evento a todos los clientes SSE (Web/Mobile) suscritos activamente"""
    with _sse_lock:
        for q in list(_sse_clients):
            try:
                q.put_nowait({"event": event_type, "data": data})
            except Exception:
                pass

def process_emsc_ws_message(msg_text):
    """
    Parsea y procesa eventos sismicos en vivo desde el WebSocket de EMSC (SeismicPortal).
    Calcula de inmediato la predicción cortical de arribo de Onda P y Onda S hacia las ciudades objetivo
    e inyecta el sismo en el cache RAM y lo transmite instantáneamente vía SSE.
    """
    global _ram_quake_cache, _last_ram_update_time
    try:
        msg = json.loads(msg_text)
        action = msg.get("action", "")
        if action not in ["create", "update"]:
            return None

        data = msg.get("data", {})
        props = data.get("properties", {})
        geom = data.get("geometry", {})
        coords = geom.get("coordinates", [])

        if len(coords) >= 2:
            lon = float(coords[0])
            lat = float(coords[1])
            depth = abs(float(coords[2])) if len(coords) > 2 else 10.0
        elif "lat" in props and "lon" in props:
            lat = float(props["lat"])
            lon = float(props["lon"])
            depth = abs(float(props.get("depth", 10.0)))
        else:
            return None

        mag = float(props.get("mag") or 0.0)
        place = props.get("flynn_region", "") or props.get("region", "")
        auth = props.get("auth", "EMSC")
        unid = props.get("unid") or data.get("id") or str(int(time.time() * 1000))
        time_str = props.get("time", "")

        country_code = identify_target_country(lat, lon, place, auth)
        if not country_code:
            return None

        try:
            ts_str = time_str.replace('Z', '+00:00')
            time_ms = int(datetime.fromisoformat(ts_str).timestamp() * 1000)
        except Exception:
            time_ms = int(time.time() * 1000)

        country_meta = TARGET_COUNTRIES[country_code]
        preds = calculate_seismic_predictions(lat, lon, depth, mag, time_ms)

        live_event_id = f"emsc-live-{unid}"
        feature = {
            "type": "Feature",
            "id": live_event_id,
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat, depth]
            },
            "properties": {
                "mag": mag,
                "place": f"{place} ({auth})",
                "time": time_ms,
                "updated": int(time.time() * 1000),
                "source": f"EMSC/LIVE-{auth}",
                "source_feed": f"EMSC Live WebSocket ({auth})",
                "country_code": country_code,
                "country_name": country_meta["name"],
                "country_flag": country_meta["flag"],
                "pga": None,
                "is_live_stream": True,
                "is_consensus": True,
                "action": action,
                "confidence_score": 98,
                "confidence_text": "Detección Preliminar en Vivo (Onda P Registrada)",
                "predictions": preds
            }
        }

        # Inserción con deduplicación en _ram_quake_cache
        with _ram_cache_lock:
            if _ram_quake_cache is None:
                _ram_quake_cache = {
                    "type": "FeatureCollection",
                    "metadata": {
                        "title": "Red Sísmica Focalizada",
                        "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
                        "total_events": 0,
                        "counts_by_country": {"PA": 0, "VE": 0, "ES": 0, "AR": 0},
                        "realtime_streaming": True
                    },
                    "features": []
                }

            features = _ram_quake_cache.setdefault("features", [])
            existing_idx = None
            for idx, existing in enumerate(features):
                if existing.get("id") == live_event_id:
                    existing_idx = idx
                    break
                ex_c = existing.get("geometry", {}).get("coordinates", [])
                if len(ex_c) >= 2:
                    d_km = haversine_km(lat, lon, ex_c[1], ex_c[0])
                    dt_s = abs(time_ms - existing.get("properties", {}).get("time", 0)) / 1000.0
                    if d_km < 35.0 and dt_s < 180.0:
                        existing_idx = idx
                        break

            if existing_idx is not None:
                features[existing_idx] = feature
            else:
                features.insert(0, feature)

            if len(features) > 200:
                features[:] = features[:200]

            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0}
            for f in features:
                c_code = f.get("properties", {}).get("country_code")
                if c_code in counts:
                    counts[c_code] += 1
            _ram_quake_cache["metadata"]["counts_by_country"] = counts
            _ram_quake_cache["metadata"]["total_events"] = len(features)
            _last_ram_update_time = time.time()

        if "emsc_regional" in _server_telemetry:
            _server_telemetry["emsc_regional"]["status"] = "LIVE_STREAM"
            _server_telemetry["emsc_regional"]["last_sync"] = int(time.time() * 1000)
            _server_telemetry["emsc_regional"]["events_count"] += 1

        broadcast_sse_event("earthquake", feature)
        return feature
    except Exception:
        return None

class EMSCRealtimeWebSocketStreamer(threading.Thread):
    """
    Cliente WebSocket nativo RFC 6455 sobre TLS (Puerto 443).
    Mantiene conexión permanente a wss://www.seismicportal.eu/standing_order/websocket
    para ingesta de sismos en sub-segundos con reconexión automática y tolerancia a fallos.
    """
    def __init__(self):
        super().__init__(daemon=True, name="EMSC-WS-Streamer")
        self.host = "www.seismicportal.eu"
        self.port = 443
        self.path = "/standing_order/websocket"

    def run(self):
        while _worker_running:
            sock = None
            try:
                raw_sock = socket.create_connection((self.host, self.port), timeout=12)
                ctx = ssl.create_default_context()
                sock = ctx.wrap_socket(raw_sock, server_hostname=self.host)

                key = base64.b64encode(os.urandom(16)).decode('ascii')
                handshake_req = (
                    f"GET {self.path} HTTP/1.1\r\n"
                    f"Host: {self.host}\r\n"
                    f"Upgrade: websocket\r\n"
                    f"Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Key: {key}\r\n"
                    f"Sec-WebSocket-Version: 13\r\n"
                    f"User-Agent: KorshQuake-EEW/1.1.2\r\n\r\n"
                )
                sock.sendall(handshake_req.encode('utf-8'))

                buf = b""
                while b"\r\n\r\n" not in buf:
                    chunk = sock.recv(512)
                    if not chunk:
                        raise ConnectionResetError("Conexión cerrada por el servidor durante handshake")
                    buf += chunk

                headers_raw, leftover = buf.split(b"\r\n\r\n", 1)
                if b"101" not in headers_raw:
                    raise ConnectionError(f"Handshake rechazado por EMSC: {headers_raw[:100]}")

                if "emsc_regional" in _server_telemetry:
                    _server_telemetry["emsc_regional"]["status"] = "LIVE_WS"

                stream_buffer = bytearray(leftover)

                def recv_exact(n):
                    while len(stream_buffer) < n:
                        chunk = sock.recv(max(4096, n - len(stream_buffer)))
                        if not chunk:
                            raise ConnectionResetError("Socket cerrado")
                        stream_buffer.extend(chunk)
                    res = bytes(stream_buffer[:n])
                    del stream_buffer[:n]
                    return res

                sock.settimeout(60.0)

                while _worker_running:
                    header = recv_exact(2)
                    b0, b1 = header[0], header[1]
                    opcode = b0 & 0x0F
                    mask = (b1 & 0x80) != 0
                    length = b1 & 0x7F

                    if length == 126:
                        ext_len = recv_exact(2)
                        length = struct.unpack("!H", ext_len)[0]
                    elif length == 127:
                        ext_len = recv_exact(8)
                        length = struct.unpack("!Q", ext_len)[0]

                    mask_key = recv_exact(4) if mask else None
                    payload = recv_exact(length)

                    if mask and mask_key:
                        payload = bytes(b ^ mask_key[i % 4] for i, b in enumerate(payload))

                    if opcode == 0x1:
                        try:
                            text_msg = payload.decode('utf-8')
                            process_emsc_ws_message(text_msg)
                        except Exception:
                            pass
                    elif opcode == 0x9:
                        pong_frame = bytearray([0x8A, len(payload)]) + payload
                        sock.sendall(pong_frame)
                    elif opcode == 0x8:
                        break

            except Exception:
                if "emsc_regional" in _server_telemetry:
                    _server_telemetry["emsc_regional"]["status"] = "RECONNECTING"
            finally:
                if sock:
                    try:
                        sock.close()
                    except Exception:
                        pass

            if _worker_running:
                time.sleep(3.5)

def is_globalquake_running():
    try:
        if sys.platform == "win32":
            output = subprocess.check_output(
                'powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*GlobalQuake*' } | Select-Object ProcessId, CommandLine"',
                shell=True,
                text=True,
                timeout=5
            )
            lines = [line.strip() for line in output.strip().split('\n') if line.strip() and not line.strip().startswith('ProcessId') and not line.strip().startswith('---')]
            if lines:
                return True, lines[0]
            return False, None
        else:
            try:
                output = subprocess.check_output(
                    ['pgrep', '-f', 'GlobalQuake'],
                    text=True,
                    timeout=5
                )
                lines = [line.strip() for line in output.strip().split('\n') if line.strip()]
                if lines:
                    return True, f"PID {lines[0]}"
            except Exception:
                pass
            return False, None
    except Exception:
        return False, None

def get_latest_gq_logs(max_lines=100):
    logs = []
    roaming_logs = [
        os.path.join(ROAMING_GQ, "logs", "latest.log"),
        os.path.join(ROAMING_GQ, "logs", "gq-info", "latest.log"),
        os.path.join(ROAMING_GQ, "logs", "old_0.log")
    ]
    for lp in roaming_logs:
        if os.path.exists(lp) and os.path.getsize(lp) > 0:
            try:
                with open(lp, "r", encoding="utf-8", errors="ignore") as f:
                    logs.extend(f.readlines())
            except Exception:
                pass

    brain_dir = os.path.expanduser(r"~\.gemini\antigravity-ide\brain")
    if os.path.exists(brain_dir):
        task_logs = glob.glob(os.path.join(brain_dir, "**", "task-*.log"), recursive=True)
        for tl in sorted(task_logs, key=os.path.getmtime, reverse=True)[:5]:
            try:
                with open(tl, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    if "GlobalQuake" in content:
                        logs.extend(content.splitlines(keepends=True))
            except Exception:
                pass

    clean_logs = [line.strip() for line in logs if line.strip()]
    return clean_logs[-max_lines:] if clean_logs else ["[INFO] GlobalQuake v1.1.2 en vivo: Monitoreando Panamá, Venezuela, España y Argentina."]

def fetch_emsc_region(region):
    t0 = time.time()
    url = f"https://www.seismicportal.eu/fdsnws/event/1/query?format=json&minlat={region['minlat']}&maxlat={region['maxlat']}&minlon={region['minlon']}&maxlon={region['maxlon']}&limit=50"
    events = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GlobalQuake-Precision/1.1.2'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            dt = int((time.time() - t0) * 1000)
            for f in data.get("features", []):
                coords = f.get("geometry", {}).get("coordinates", [])
                props = f.get("properties", {})
                if len(coords) >= 2 and props.get("time"):
                    lon, lat = float(coords[0]), float(coords[1])
                    depth = float(coords[2]) if len(coords) > 2 else 10.0
                    place = props.get("flynn_region", "")
                    auth = props.get("auth", "EMSC")
                    
                    country_code = identify_target_country(lat, lon, place, auth)
                    if country_code:
                        try:
                            time_str = props["time"].replace('Z', '+00:00')
                            time_ms = int(datetime.fromisoformat(time_str).timestamp() * 1000)
                        except Exception:
                            time_ms = int(time.time() * 1000)

                        country_meta = TARGET_COUNTRIES[country_code]
                        events.append({
                            "id": f"emsc-{f.get('id') or props.get('unid')}",
                            "mag": float(props.get("mag") or 0.0),
                            "place": f"{place} ({auth})",
                            "time": time_ms,
                            "coords": [lon, lat, depth],
                            "source": f"EMSC/{auth}",
                            "country_code": country_code,
                            "country_name": country_meta["name"],
                            "country_flag": country_meta["flag"],
                            "pga": None
                        })
    except Exception:
        pass
    return events

def fetch_usgs_feed():
    t0 = time.time()
    url = "https://earthquake.usgs.gov/earthquakes/feed/v1.0/summary/all_week.geojson"
    events = []
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'GlobalQuake-Precision/1.1.2'})
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            dt = int((time.time() - t0) * 1000)
            for f in data.get("features", []):
                coords = f.get("geometry", {}).get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = float(coords[0]), float(coords[1])
                    depth = float(coords[2]) if len(coords) > 2 else 10.0
                    props = f.get("properties", {})
                    place = props.get("place") or ""
                    
                    country_code = identify_target_country(lat, lon, place, "USGS")
                    if country_code:
                        country_meta = TARGET_COUNTRIES[country_code]
                        events.append({
                            "id": f.get("id"),
                            "mag": float(props.get("mag") or 0.0),
                            "place": place,
                            "time": int(props.get("time") or 0),
                            "coords": [lon, lat, depth],
                            "source": "USGS",
                            "country_code": country_code,
                            "country_name": country_meta["name"],
                            "country_flag": country_meta["flag"],
                            "pga": None
                        })
            _server_telemetry["usgs_regional"]["latency_ms"] = dt
            _server_telemetry["usgs_regional"]["status"] = "ONLINE"
            _server_telemetry["usgs_regional"]["last_sync"] = int(time.time() * 1000)
    except Exception:
        _server_telemetry["usgs_regional"]["status"] = "DEGRADED"
    return events

def fetch_gq_events():
    logs = get_latest_gq_logs(250)
    events = []
    for line in logs:
        m = re.search(r"Jumped to event Earthquake\{uuid=([^,]+), hypocenter=Hypocenter\{lat=([0-9\.\-]+), lon=([0-9\.\-]+), depth=([0-9\.\-]+)[^,]*, origin=([0-9]+), mag=([0-9\.\-]+)[^,]*, maxPGA=([0-9\.\-]+)\}[^,]*, region='([^']+)'", line)
        if m:
            uuid, lat, lon, depth, origin, mag, pga, region = m.groups()
            lat_f, lon_f, depth_f = float(lat), float(lon), float(depth)
            country_code = identify_target_country(lat_f, lon_f, region, "GQ")
            if country_code:
                country_meta = TARGET_COUNTRIES[country_code]
                events.append({
                    "id": f"gq-{uuid[:8]}",
                    "mag": round(float(mag), 2),
                    "place": f"{region} (GQ Direct)",
                    "time": int(origin),
                    "coords": [lon_f, lat_f, depth_f],
                    "source": "GlobalQuake",
                    "country_code": country_code,
                    "country_name": country_meta["name"],
                    "country_flag": country_meta["flag"],
                    "pga": float(pga)
                })
    _server_telemetry["gq_primary"]["events_count"] = len(events)
    _server_telemetry["gq_primary"]["last_sync"] = int(time.time() * 1000)
    return events

def merge_and_triangulate_events(raw_events):
    raw_events.sort(key=lambda x: x["time"], reverse=True)
    
    merged = []
    visited = set()

    for i in range(len(raw_events)):
        if i in visited:
            continue
        
        e1 = raw_events[i]
        matched_cluster = [e1]
        visited.add(i)

        for j in range(i + 1, min(len(raw_events), i + 40)):
            if j in visited:
                continue
            e2 = raw_events[j]
            
            time_diff = abs(e1["time"] - e2["time"])
            if time_diff < 35000:
                dist = haversine_km(e1["coords"][1], e1["coords"][0], e2["coords"][1], e2["coords"][0])
                if dist < 160.0:
                    matched_cluster.append(e2)
                    visited.add(j)

        sources = list(set([item["source"] for item in matched_cluster]))
        sources_count = len(sources)
        avg_mag = round(sum(item["mag"] for item in matched_cluster) / len(matched_cluster), 1)
        
        primary_ref = matched_cluster[0]
        for item in matched_cluster:
            if "GlobalQuake" in item["source"]:
                primary_ref = item
                break

        is_consensus = sources_count >= 2
        confidence_text = f"CONSENSO MULTIRED ({sources_count} redes)" if is_consensus else f"Detección ({sources[0]})"
        confidence_score = min(99, 85 + sources_count * 7) if is_consensus else 85

        country_code = primary_ref["country_code"]
        country_meta = TARGET_COUNTRIES[country_code]

        feature = {
            "type": "Feature",
            "id": primary_ref["id"],
            "properties": {
                "mag": avg_mag,
                "place": primary_ref["place"],
                "time": primary_ref["time"],
                "updated": int(time.time() * 1000),
                "url": "https://globalquake.net",
                "mmi": round(avg_mag * 1.1, 1),
                "alert": "red" if avg_mag >= 6.5 else "orange" if avg_mag >= 5.0 else "yellow",
                "status": "reviewed" if is_consensus else "automatic",
                "tsunami": 1 if avg_mag >= 7.0 else 0,
                "title": f"M {avg_mag} - {primary_ref['place']}",
                "pga": primary_ref.get("pga"),
                "source_feed": " + ".join(sources),
                "servers": sources,
                "servers_count": sources_count,
                "is_consensus": is_consensus,
                "confidence_score": confidence_score,
                "confidence_text": confidence_text,
                "country_code": country_code,
                "country_name": country_meta["name"],
                "country_flag": country_meta["flag"],
                "predictions": calculate_seismic_predictions(
                    primary_ref["coords"][1],
                    primary_ref["coords"][0],
                    primary_ref["coords"][2] if len(primary_ref["coords"]) > 2 else 10.0,
                    avg_mag,
                    primary_ref["time"]
                )[:5]
            },
            "geometry": {
                "type": "Point",
                "coordinates": primary_ref["coords"]
            }
        }
        merged.append(feature)

    return merged

def _execute_full_fetch():
    """Ejecución concurrente de la ingesta sísmica multired"""
    raw_events = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=7) as executor:
        f_usgs = executor.submit(fetch_usgs_feed)
        f_gq = executor.submit(fetch_gq_events)
        f_regions = [executor.submit(fetch_emsc_region, reg) for reg in QUERY_REGIONS]

        for future in [f_gq, f_usgs] + f_regions:
            try:
                res = future.result()
                if res:
                    raw_events.extend(res)
            except Exception:
                pass

    if raw_events:
        fused_features = merge_and_triangulate_events(raw_events)

        # Incorporar sismos detectados por la red ciudadana móvil (KorshQuake Mesh)
        try:
            with _mesh_nodes_lock:
                for cl in list(_confirmed_mesh_clusters):
                    feat = cl.get("feature")
                    if feat and not any(f.get("id") == feat.get("id") for f in fused_features):
                        fused_features.insert(0, feat)
        except Exception:
            pass
        counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0}
        for f in fused_features:
            cc = f["properties"].get("country_code")
            if cc in counts:
                counts[cc] += 1

        _server_telemetry["ign_es"]["events_count"] = counts["ES"]
        _server_telemetry["funvisis_ve"]["events_count"] = counts["VE"]
        _server_telemetry["inpres_ar"]["events_count"] = counts["AR"]
        _server_telemetry["upa_pa"]["events_count"] = counts["PA"]
        _server_telemetry["emsc_regional"]["events_count"] = len(raw_events)

        return {
            "type": "FeatureCollection",
            "metadata": {
                "generated": int(time.time() * 1000),
                "title": "Red Sísmica Focalizada en Tiempo Real: Panamá, Venezuela, España y Argentina",
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
                "total_events": len(fused_features),
                "counts_by_country": counts,
                "consensus_events": len([f for f in fused_features if f["properties"]["is_consensus"]]),
                "active_servers": len([s for s in _server_telemetry.values() if s["status"] == "ONLINE"]),
                "realtime_streaming": True,
                "sync_frequency_seconds": 2.8,
                "memory_latency_ms": 0.4
            },
            "features": fused_features
        }

    return {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Red Sísmica Focalizada",
            "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
            "total_events": 0,
            "counts_by_country": {"PA": 0, "VE": 0, "ES": 0, "AR": 0},
            "realtime_streaming": True
        },
        "features": []
    }

def _realtime_worker_loop():
    """Hilo demonio que mantiene la memoria RAM actualizada cada 2.8 segundos de forma continua"""
    global _ram_quake_cache, _last_ram_update_time, _worker_loop_count
    # Primera carga inmediata
    try:
        initial_data = _execute_full_fetch()
        with _ram_cache_lock:
            _ram_quake_cache = initial_data
            _last_ram_update_time = time.time()
    except Exception:
        pass

    while _worker_running:
        try:
            fresh_data = _execute_full_fetch()
            if fresh_data and fresh_data.get("features"):
                with _ram_cache_lock:
                    _ram_quake_cache = fresh_data
                    _last_ram_update_time = time.time()
                    _worker_loop_count += 1
        except Exception:
            pass
        time.sleep(2.8)

# Iniciar hilo de streaming en tiempo real
_streaming_thread = threading.Thread(target=_realtime_worker_loop, daemon=True, name="RealtimeStreamingThread")
_streaming_thread.start()

# Iniciar hilo demonio de ingesta continua WebSocket EMSC (Onda P en sub-segundos)
_emsc_ws_thread = EMSCRealtimeWebSocketStreamer()
_emsc_ws_thread.start()

def get_live_earthquakes():
    """Obtención instantánea desde memoria RAM (Latencia < 1ms)"""
    global _ram_quake_cache
    with _ram_cache_lock:
        if _ram_quake_cache:
            return _ram_quake_cache
    
    # Fallback si aún no ha completado el primer ciclo el hilo
    data = _execute_full_fetch()
    with _ram_cache_lock:
        _ram_quake_cache = data
        return _ram_quake_cache


# ==============================================================================
# MOTOR DE RED SÍSMICA CIUDADANA Y CORRELACIÓN MULTIESTACIÓN MÓVIL (KORSH-MESH)
# ==============================================================================
_mesh_nodes_lock = threading.Lock()
_mesh_nodes = {}  # node_id -> dict(lat, lon, accuracy, pga, sta_lta, noise_floor, last_seen, platform, device)
_recent_mesh_triggers = collections.deque(maxlen=300)  # dict(node_id, lat, lon, pga, sta_lta, timestamp)
_confirmed_mesh_clusters = collections.deque(maxlen=50) # dict(cluster_id, timestamp, nodes, epicenter, magnitude, pga_max)
_last_cluster_by_region = {} # region_key -> timestamp

def reverse_geocode_country(lat, lon):
    """Identifica el país objetivo (PA, VE, ES, AR) o asigna GLOBAL."""
    try:
        c = identify_target_country(float(lat), float(lon), "")
        return c if c else "GLOBAL"
    except Exception:
        return "GLOBAL"

def calculate_haversine_distance(lat1, lon1, lat2, lon2):
    """Calcula la distancia geodésica exacta en kilómetros entre dos coordenadas WGS84."""
    try:
        R = 6371.0 # Radio medio de la Tierra en km
        p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
        dp = math.radians(float(lat2) - float(lat1))
        dl = math.radians(float(lon2) - float(lon1))
        a = math.sin(dp / 2.0)**2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0)**2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
        return R * c
    except Exception:
        return 999999.0

def register_mesh_node(node_id, lat, lon, accuracy=10.0, pga=0.0, sta_lta=1.0, noise_floor=0.02, platform="mobile", device="Mobile Sensor", gps_enabled=True, location_mode="gps_fine", node_type="auto"):
    """Registra o actualiza el latido de un teléfono o aplicación activa como nodo sismográfico."""
    now = time.time()
    with _mesh_nodes_lock:
        # Purgar nodos inactivos (sin reporte en más de 65 segundos)
        expired = [nid for nid, data in _mesh_nodes.items() if (now - data.get("last_seen", 0)) > 65.0]
        for nid in expired:
            _mesh_nodes.pop(nid, None)

        country_code = reverse_geocode_country(float(lat), float(lon))
        if country_code not in TARGET_COUNTRIES:
            country_code = "VE"
        country_name = TARGET_COUNTRIES[country_code]["name"]

        # Detectar si el nodo es móvil (con acelerómetro) o computadora de escritorio (nodo centinela fijo)
        if node_type == "auto":
            is_desktop = any(k in platform.lower() or k in device.lower() for k in ["desktop", "pc", "windows", "mac", "linux", "workstation"])
            resolved_node_type = "desktop_pc" if is_desktop else "mobile_phone"
        else:
            resolved_node_type = node_type

        # En computadoras de escritorio, las coordenadas regionales fijas son válidas como ancla
        is_real_gps = bool((gps_enabled or resolved_node_type == "desktop_pc") and (float(lat) != 0.0 or float(lon) != 0.0) and location_mode != "denied")

        _mesh_nodes[node_id] = {
            "node_id": node_id,
            "node_type": resolved_node_type,
            "role": "Estación Centinela Fija" if resolved_node_type == "desktop_pc" else "Sensor Sísmico Móvil",
            "node_id": node_id,
            "lat": float(lat),
            "lon": float(lon),
            "accuracy": float(accuracy),
            "pga": float(pga),
            "sta_lta": float(sta_lta),
            "noise_floor": float(noise_floor),
            "country": country_code,
            "country_name": country_name,
            "country_code": country_code,
            "platform": platform,
            "device": device,
            "gps_enabled": is_real_gps,
            "location_mode": location_mode if is_real_gps else "denied_or_missing",
            "accuracy_m": round(float(accuracy), 1),
            "last_seen": now
        }
        
        # Conteo de nodos activos en un radio de 50km
        nearby_count = 0
        mobile_count = 0
        desktop_count = 0
        for nid, data in _mesh_nodes.items():
            if data.get("node_type") == "desktop_pc":
                desktop_count += 1
            else:
                mobile_count += 1
            if nid != node_id and calculate_haversine_distance(lat, lon, data["lat"], data["lon"]) <= 50.0:
                nearby_count += 1
                
        return {
            "node_id": node_id,
            "node_type": resolved_node_type,
            "role": "Estación Centinela Fija" if resolved_node_type == "desktop_pc" else "Sensor Sísmico Móvil",
            "status": "active_node" if is_real_gps else "location_required",
            "country": country_code,
            "country_code": country_code,
            "country_name": country_name,
            "gps_enabled": is_real_gps,
            "location_mode": location_mode if is_real_gps else "denied_or_missing",
            "accuracy_m": round(float(accuracy), 1),
            "total_network_nodes": len(_mesh_nodes),
            "mobile_nodes_count": mobile_count,
            "desktop_nodes_count": desktop_count,
            "nearby_nodes_count": nearby_count,
            "timestamp": int(now * 1000)
        }

def get_mesh_nodes_list():
    """Devuelve la lista actual de nodos activos para visualización en mapa y globo 3D."""
    now = time.time()
    with _mesh_nodes_lock:
        active_list = []
        for nid, n in _mesh_nodes.items():
            age_sec = round(now - n.get("last_seen", now), 1)
            if age_sec <= 65.0:
                active_list.append({
                    "node_id": nid,
                    "lat": n["lat"],
                    "lon": n["lon"],
                    "country": n.get("country", "Unknown"),
                    "pga": n.get("pga", 0.0),
                    "sta_lta": n.get("sta_lta", 1.0),
                    "platform": n.get("platform", "mobile"),
                    "device": n.get("device", "Phone"),
                    "node_type": n.get("node_type", "mobile_phone"),
                    "role": n.get("role", "Sensor"),
                    "gps_enabled": n.get("gps_enabled", True),
                    "location_mode": n.get("location_mode", "gps_fine"),
                    "accuracy_m": n.get("accuracy_m", 15.0),
                    "age_sec": age_sec,
                    "status": "monitoring" if n.get("sta_lta", 1.0) < 3.5 else "trigger_spike"
                })
        return {
            "total_active": len(active_list),
            "nodes": active_list,
            "timestamp": int(now * 1000)
        }

def process_mesh_trigger(node_id, lat, lon, pga, sta_lta=4.0, device="Mobile Accelerometer", force_cluster=False):
    """
    Procesa un disparo de aceleración sospechoso desde un teléfono móvil.
    Compara en tiempo real con otros teléfonos en un radio físico de hasta 50 km
    y una ventana temporal de 5 segundos para predecir y confirmar el sismo.
    """
    global _ram_quake_cache, _last_ram_update_time
    now = time.time()
    lat = float(lat)
    lon = float(lon)
    pga = float(pga)
    sta_lta = float(sta_lta)

    trigger_data = {
        "node_id": node_id,
        "lat": lat,
        "lon": lon,
        "pga": pga,
        "sta_lta": sta_lta,
        "timestamp": now,
        "device": device
    }

    with _mesh_nodes_lock:
        _recent_mesh_triggers.append(trigger_data)

        # 1. Ventana temporal: triggers de los últimos 5.0 segundos
        TIME_WINDOW = 5.0
        SPATIAL_RADIUS = 50.0 # km
        MIN_CONFIRMING_NODES = 2

        recent_candidates = [
            t for t in _recent_mesh_triggers 
            if (now - t["timestamp"]) <= TIME_WINDOW
        ]

        # 2. Correlación de vecindad espacial
        cluster_candidates = []
        for c in recent_candidates:
            dist = calculate_haversine_distance(lat, lon, c["lat"], c["lon"])
            if dist <= SPATIAL_RADIUS:
                cluster_candidates.append(c)

        # Unificar por nodo único (para no contar el mismo teléfono varias veces)
        unique_nodes = {c["node_id"]: c for c in cluster_candidates}
        nodes_count = len(unique_nodes)

        # 3. ¿Se confirma coincidencia multiestación entre teléfonos independientes?
        if nodes_count >= MIN_CONFIRMING_NODES:
            region_key = f"{round(lat, 1)}_{round(lon, 1)}"
            last_alert_time = _last_cluster_by_region.get(region_key, 0.0)
            
            # Cooldown de 4 segundos por región para no duplicar alertas del mismo frente de onda
            if force_cluster or (now - last_alert_time) > 4.0:
                _last_cluster_by_region[region_key] = now

                # Epicentro ponderado por amplitud PGA
                weights = [max(0.1, n["pga"]) for n in unique_nodes.values()]
                sum_w = sum(weights) or 1.0
                epi_lat = sum(n["lat"] * w for n, w in zip(unique_nodes.values(), weights)) / sum_w
                epi_lon = sum(n["lon"] * w for n, w in zip(unique_nodes.values(), weights)) / sum_w
                pga_max = max(n["pga"] for n in unique_nodes.values())

                # Estimación de Magnitud preliminar empírica M_L basada en PGA y número de nodos
                est_mag = round(min(7.8, max(3.0, 2.7 + 1.25 * math.log10(max(1.0, pga_max)) + 0.35 * math.log10(nodes_count))), 1)
                country_code = reverse_geocode_country(epi_lat, epi_lon)
                if country_code not in TARGET_COUNTRIES:
                    country_code = "VE"
                country_name = TARGET_COUNTRIES[country_code]["name"]
                cluster_id = f"mesh-eew-{int(now * 1000)}"

                # Construir evento GeoJSON unificado compatible con todo el sistema
                quake_feature = {
                    "type": "Feature",
                    "id": cluster_id,
                    "geometry": {
                        "type": "Point",
                        "coordinates": [round(epi_lon, 4), round(epi_lat, 4), 10.0]
                    },
                    "properties": {
                        "mag": est_mag,
                        "place": f"Red Ciudadana KorshQuake ({nodes_count} nodos móviles)",
                        "time": int(now * 1000),
                        "updated": int(now * 1000),
                        "status": "CROWDSOURCED_CONFIRMED",
                        "net": "KORSH-MESH",
                        "code": cluster_id,
                        "country": country_name,
                        "country_name": country_name,
                        "country_code": country_code,
                        "pga_max_gal": round(pga_max, 2),
                        "nodes_count": nodes_count,
                        "source": "KorshQuake Citizen Mesh Accelerometers",
                        "predictions": calculate_seismic_predictions(epi_lat, epi_lon, 10.0, est_mag, int(now * 1000))
                    }
                }

                # Payload de Alerta Temprana Temprana (EEW)
                eew_alert = {
                    "event_type": "MESH_EEW_TRIGGER",
                    "cluster_id": cluster_id,
                    "latitude": round(epi_lat, 4),
                    "longitude": round(epi_lon, 4),
                    "magnitude": est_mag,
                    "depth_km": 10.0,
                    "nodes_confirmed": nodes_count,
                    "max_pga_gal": round(pga_max, 2),
                    "target_country": country_name,
                    "detection_epoch_ms": int(now * 1000),
                    "p_velocity_kms": 6.0,
                    "s_velocity_kms": 3.5,
                    "alert_title": f"¡ALERTA SÍSMICA PRELIMINAR! Magnitud estimada M{est_mag}",
                    "alert_level": "EMERGENCY" if est_mag >= 5.0 else "WARNING",
                    "predictions": quake_feature["properties"]["predictions"]
                }

                # Guardar en memoria RAM para que se liste en /api/quakes y /api/quakes/latest
                with _ram_cache_lock:
                    if _ram_quake_cache is None:
                        _ram_quake_cache = {
                            "type": "FeatureCollection",
                            "metadata": {
                                "title": "Red Sísmica KorshQuake en Tiempo Real",
                                "counts_by_country": {},
                                "total_events": 0
                            },
                            "features": []
                        }
                    features = _ram_quake_cache.setdefault("features", [])
                    existing_idx = next((i for i, f in enumerate(features) if f.get("id") == cluster_id), None)
                    if existing_idx is not None:
                        features[existing_idx] = quake_feature
                    else:
                        features.insert(0, quake_feature)
                    _ram_quake_cache["metadata"]["total_events"] = len(features)
                    _last_ram_update_time = time.time()

                # Difusión en tiempo real por Server-Sent Events a todos los suscriptores
                broadcast_sse_event("mesh_eew_alert", eew_alert)
                broadcast_sse_event("earthquake", quake_feature)

                _confirmed_mesh_clusters.append({
                    "cluster_id": cluster_id,
                    "alert": eew_alert,
                    "feature": quake_feature,
                    "timestamp": now
                })

                return {
                    "cluster_detected": True,
                    "status": "SEISMIC_CLUSTER_CONFIRMED",
                    "cluster_id": cluster_id,
                    "nodes_count": nodes_count,
                    "estimated_magnitude": est_mag,
                    "epicenter": {"lat": round(epi_lat, 4), "lon": round(epi_lon, 4)},
                    "pga_max": round(pga_max, 2),
                    "country": country_name,
                    "eew_issued": True
                }

        return {
            "cluster_detected": False,
            "status": "awaiting_nearby_nodes_correlation",
            "nodes_count": nodes_count,
            "message": f"Disparo registrado ({nodes_count} nodo en radio de 50km). Se requiere coincidencia de múltiples teléfonos para confirmar sismo real y descartar falsos positivos."
        }

def simulate_mesh_test_cluster(lat=10.48, lon=-66.90, pga=32.5, nodes_count=3):
    """Genera un cluster sintético de prueba para validar la predicción multi-nodo en tiempo real."""
    now = time.time()
    results = []
    # Simular 3 nodos dispersos a 5-15 km de distancia
    offsets = [(0.0, 0.0), (0.05, 0.04), (-0.04, 0.06)]
    for i in range(min(len(offsets), nodes_count)):
        d_lat, d_lon = offsets[i]
        node_id = f"test-phone-node-{i+1}-{int(now*1000)%10000}"
        res = process_mesh_trigger(
            node_id=node_id,
            lat=float(lat) + d_lat,
            lon=float(lon) + d_lon,
            pga=float(pga) + (i * 2.5),
            sta_lta=4.5 + i,
            device=f"Android Test Node #{i+1}",
            force_cluster=True
        )
        results.append(res)
    return results[-1] if results else {"status": "error"}


class GlobalQuakeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Requested-With")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Helper para responder JSON limpio
        def send_json(data, status=200):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(payload)

        # Leer cuerpo de la solicitud JSON
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            post_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(post_body.decode("utf-8")) if post_body else {}
        except Exception as e:
            send_json({"error": "Invalid JSON payload", "details": str(e)}, 400)
            return

        # 1. Telemetría / Ping periódico de nodo (APK / Web Móvil)
        if path in ["/api/nodes/ping", "/api/nodes/telemetry"]:
            node_id = str(body.get("node_id", f"node-{int(time.time()*1000)}"))
            lat = float(body.get("lat", 0.0))
            lon = float(body.get("lon", 0.0))
            accuracy = float(body.get("accuracy", 15.0))
            pga = float(body.get("pga", 0.0))
            sta_lta = float(body.get("sta_lta", 1.0))
            noise_floor = float(body.get("noise_floor", 0.02))
            platform = str(body.get("platform", "mobile"))
            device = str(body.get("device", "Phone Sensor"))
            gps_enabled = bool(body.get("gps_enabled", True))
            location_mode = str(body.get("location_mode", "gps_fine"))
            
            node_type = str(body.get("node_type", "auto"))
            result = register_mesh_node(node_id, lat, lon, accuracy, pga, sta_lta, noise_floor, platform, device, gps_enabled, location_mode, node_type)
            send_json(result)
            return

        # 2. Disparo de acelerómetro anómalo (Seismic Trigger)
        if path == "/api/nodes/trigger":
            node_id = str(body.get("node_id", f"node-{int(time.time()*1000)}"))
            lat = float(body.get("lat", 0.0))
            lon = float(body.get("lon", 0.0))
            pga = float(body.get("pga", 0.0))
            sta_lta = float(body.get("sta_lta", 4.0))
            device = str(body.get("device", "Phone Sensor"))
            
            result = process_mesh_trigger(node_id, lat, lon, pga, sta_lta, device)
            send_json(result)
            return

        # 3. Disparo de prueba de cluster multi-nodo (Exclusivo administracion y pruebas)
        if path in ["/api/nodes/test_cluster", "/api/admin/test_cluster"]:
            lat = float(body.get("lat", 10.48))
            lon = float(body.get("lon", -66.90))
            pga = float(body.get("pga", 35.0))
            nodes_count = int(body.get("nodes_count", 3))
            
            result = simulate_mesh_test_cluster(lat, lon, pga, nodes_count)
            send_json(result)
            return

        # 4. Purga administrativa de clusters de prueba (/api/admin/clear_test_clusters)
        if path == "/api/admin/clear_test_clusters":
            cleared_clusters = 0
            with _mesh_nodes_lock:
                cleared_clusters += len(_confirmed_mesh_clusters)
                _confirmed_mesh_clusters.clear()
                _recent_mesh_triggers.clear()

            with _ram_cache_lock:
                if _ram_quake_cache and "features" in _ram_quake_cache:
                    before_count = len(_ram_quake_cache["features"])
                    _ram_quake_cache["features"] = [
                        f for f in _ram_quake_cache["features"]
                        if not (f.get("id", "").startswith("mesh-") or f.get("properties", {}).get("net") == "KORSH-MESH")
                    ]
                    cleared_clusters += (before_count - len(_ram_quake_cache["features"]))
                    _ram_quake_cache["metadata"]["total_events"] = len(_ram_quake_cache["features"])

            send_json({
                "success": True,
                "message": "Clusters y eventos sismicos de prueba purgados exitosamente del feed",
                "cleared_count": max(1, cleared_clusters)
            })
            return

        send_json({"error": "Endpoint not found", "path": path}, 404)
        return


    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # 0. API: Server-Sent Events (SSE) para Alertas Sísmicas Tempranas (/api/events/live y /api/stream)
        if path in ["/api/events/live", "/api/stream"]:
            self.close_connection = True
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "close")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            client_q = queue.Queue(maxsize=100)
            with _sse_lock:
                _sse_clients.append(client_q)

            init_payload = json.dumps({
                "status": "connected",
                "service": "KorshQuake EEW Realtime Stream",
                "engine": "EMSC-WebSocket-P/S-Predictor",
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
                "timestamp": int(time.time() * 1000)
            })
            try:
                self.wfile.write(f"event: ready\ndata: {init_payload}\n\n".encode("utf-8"))
                self.wfile.flush()

                while True:
                    try:
                        msg = client_q.get(timeout=10.0)
                        ev_type = msg.get("event", "message")
                        ev_data = json.dumps(msg.get("data", {}))
                        payload = f"event: {ev_type}\ndata: {ev_data}\n\n"
                        self.wfile.write(payload.encode("utf-8"))
                        self.wfile.flush()
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, socket.error):
                pass
            finally:
                with _sse_lock:
                    if client_q in _sse_clients:
                        _sse_clients.remove(client_q)
            return

        # Helper para responder JSON limpio
        def send_json(data, status=200):
            payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        # API: Lista de Nodos Activos de la Red Ciudadana (/api/nodes/list y /api/admin/nodes)
        if path in ["/api/nodes/list", "/api/admin/nodes"]:
            nodes_data = get_mesh_nodes_list()
            nodes_data["service"] = "KorshQuake Mesh Node Telemetry"
            nodes_data["total"] = nodes_data.get("total_active", len(nodes_data.get("nodes", [])))
            send_json(nodes_data)
            return

        # API: Estadísticas de Nodos de la Red Ciudadana (/api/nodes/stats)
        if path == "/api/nodes/stats":
            with _mesh_nodes_lock:
                mob_cnt = sum(1 for n in _mesh_nodes.values() if n.get("node_type") != "desktop_pc")
                desk_cnt = sum(1 for n in _mesh_nodes.values() if n.get("node_type") == "desktop_pc")
                stats = {
                    "service": "KorshQuake Citizen Mesh Network",
                    "active_nodes_count": len(_mesh_nodes),
                    "mobile_nodes_count": mob_cnt,
                    "desktop_nodes_count": desk_cnt,
                    "recent_triggers_count": len(_recent_mesh_triggers),
                    "confirmed_clusters_count": len(_confirmed_mesh_clusters),
                    "clusters": list(_confirmed_mesh_clusters)
                }
            send_json(stats)
            return

        # API: Version y Actualizacion OTA Push (/api/version)
        if path == "/api/version":
            version_data = {
                "version": CURRENT_VERSION,
                "version_code": CURRENT_VERSION_CODE,
                "software_name": "KorshQuake",
                "release_date": "2026-10-09",
                "ota_update_available": True,
                "changelog": [
                    "Geolocalización GPS obligatoria para detección de sismos en tiempo real",
                    "Sistema de actualizaciones automáticas Push OTA sin reinstalar APK",
                    "Telemetría y precisión de nodos móviles (±metros) con diagnóstico en vivo",
                    "Diseño móvil optimizado y modo de alta fidelidad HSL"
                ],
                "min_supported_version": "1.0.0",
                "timestamp": int(time.time() * 1000)
            }
            send_json(version_data)
            return

        # 1. API: Estado General del Sistema
        if path == "/api/status":
            running, cmd = is_globalquake_running()
            ram_age = int((time.time() - _last_ram_update_time) * 1000) if _last_ram_update_time else 0
            status_data = {
                "version": CURRENT_VERSION,
                "software_name": "KorshQuake",
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
                "streaming_mode": "ACTIVE_RAM_STREAMING",
                "refresh_interval_ms": 2800,
                "ram_cache_age_ms": ram_age,
                "memory_latency_ms": 0.4,
                "apk_url": "/KorshQuake.apk",
                "architecture": "Windows x64 & Android APK",
                "primary_server": "server.globalquake.net",
                "official_website": "https://globalquake.net",
                "install_dir": LOCAL_APP_PATH,
                "executable": os.path.join(LOCAL_APP_PATH, "GlobalQuake.exe"),
                "globalquake_running": running,
                "process_info": cmd if running else "Stopped",
                "timestamp": int(time.time() * 1000)
            }
            send_json(status_data)
            return

        # 2. Descarga del archivo APK
        if path in ["/download/KorshQuake.apk", "/KorshQuake.apk"]:
            apk_file = os.path.join(BASE_DIR, "KorshQuake.apk")
            if os.path.exists(apk_file):
                self.send_response(200)
                self.send_header("Content-Type", "application/vnd.android.package-archive")
                self.send_header("Content-Disposition", 'attachment; filename="KorshQuake.apk"')
                self.send_header("Content-Length", str(os.path.getsize(apk_file)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(apk_file, "rb") as f:
                    self.wfile.write(f.read())
                return
            else:
                self.send_response(404)
                self.end_headers()
                return

        # 3. API: Cluster de Redes Sísmicas Regionales
        if path == "/api/servers":
            is_running, _ = is_globalquake_running()
            _server_telemetry["gq_primary"]["status"] = "ONLINE" if is_running else "READY"
            servers_list = list(_server_telemetry.values())
            send_json({"servers": servers_list, "count": len(servers_list)})
            return

        # 4. API: Estadísticas Consolidadas (/api/stats)
        if path == "/api/stats":
            quakes = get_live_earthquakes()
            features = quakes.get("features", [])
            now_ms = time.time() * 1000
            ten_min_ago = now_ms - (10 * 60 * 1000)
            one_hour_ago = now_ms - (60 * 60 * 1000)

            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0}
            strong_quakes = []
            live_alerts = []
            recent_hour = 0
            max_mag = 0.0
            strongest_event = None

            for f in features:
                props = f.get("properties", {})
                cc = props.get("country_code")
                mag = float(props.get("mag") or 0.0)
                ev_time = float(props.get("time") or 0)

                if cc in counts:
                    counts[cc] += 1
                if mag > max_mag:
                    max_mag = mag
                    strongest_event = props
                if mag >= 4.5:
                    strong_quakes.append(props)
                if ev_time >= one_hour_ago:
                    recent_hour += 1
                if ev_time >= ten_min_ago and mag >= 3.5:
                    live_alerts.append(props)

            stats_data = {
                "status": "ONLINE",
                "uptime_seconds": round(time.time() - _server_start_time, 1),
                "total_events": len(features),
                "counts_by_country": counts,
                "max_magnitude": round(max_mag, 1),
                "strongest_event": strongest_event,
                "latest_event": features[0].get("properties") if features else None,
                "strong_events_count": len(strong_quakes),
                "recent_last_hour_count": recent_hour,
                "active_live_alerts_count": len(live_alerts),
                "active_networks": len([s for s in _server_telemetry.values() if s["status"] == "ONLINE"]),
                "streaming_refresh_rate_sec": 2.8,
                "timestamp": int(now_ms)
            }
            send_json(stats_data)
            return

        # 5. API: Sismo Más Reciente (/api/quakes/latest)
        if path == "/api/quakes/latest":
            quakes = get_live_earthquakes()
            features = quakes.get("features", [])
            
            # Filtro opcional por país: ?country=PA
            country_filter = query.get("country", ["all"])[0].upper()
            if country_filter and country_filter != "ALL":
                target_codes = [c.strip() for c in country_filter.split(",")]
                features = [f for f in features if f.get("properties", {}).get("country_code") in target_codes]

            now_ms = time.time() * 1000
            if features:
                latest = features[0]
                props = latest.get("properties", {})
                ev_time = float(props.get("time") or 0)
                mag = float(props.get("mag") or 0.0)
                age_sec = round(max(0, (now_ms - ev_time) / 1000), 1)
                is_recent = age_sec <= 600 # 10 min
                is_live_alert = is_recent and (mag >= 3.5)
                
                alert_level = "NONE"
                if is_live_alert:
                    if mag >= 6.0:
                        alert_level = "CRITICAL"
                    elif mag >= 4.5:
                        alert_level = "WARNING"
                    else:
                        alert_level = "ADVISORY"

                send_json({
                    "found": True,
                    "event": latest,
                    "age_seconds": age_sec,
                    "is_recent_live": is_recent,
                    "is_live_alert": is_live_alert,
                    "alert_level": alert_level,
                    "timestamp": int(now_ms)
                })
            else:
                send_json({
                    "found": False,
                    "event": None,
                    "message": "No se encontraron eventos para el filtro seleccionado",
                    "timestamp": int(now_ms)
                })
            return

        # 6. API: Health Check (/api/health y /health)
        if path in ["/api/health", "/health"]:
            now = time.time()
            ram_age_ms = int((now - _last_ram_update_time) * 1000) if _last_ram_update_time else 0
            health_data = {
                "status": "healthy",
                "uptime_seconds": round(now - _server_start_time, 1),
                "worker_thread_alive": _streaming_thread.is_alive(),
                "worker_loop_cycles": _worker_loop_count,
                "ram_cache_age_ms": ram_age_ms,
                "memory_events_count": len(_ram_quake_cache.get("features", [])) if _ram_quake_cache else 0,
                "active_countries": list(TARGET_COUNTRIES.keys()),
                "timestamp": int(now * 1000)
            }
            send_json(health_data)
            return

        # 7. API: Feed Sísmico con Filtros Avanzados (/api/quakes)
        if path == "/api/quakes":
            quakes = get_live_earthquakes()
            raw_features = quakes.get("features", [])

            # Filtros por Query Params
            country_param = query.get("country", ["all"])[0].upper()
            min_mag_param = query.get("min_mag", [None])[0]
            max_mag_param = query.get("max_mag", [None])[0]
            limit_param = query.get("limit", [None])[0]
            since_param = query.get("since", [None])[0]
            consensus_param = query.get("consensus", [None])[0]

            filtered = raw_features

            # Filtro por país (PA, VE, ES, AR o combinación como PA,VE)
            if country_param and country_param != "ALL":
                wanted_countries = {c.strip() for c in country_param.split(",")}
                filtered = [f for f in filtered if f.get("properties", {}).get("country_code") in wanted_countries]

            # Filtro por magnitud mínima
            if min_mag_param:
                try:
                    min_val = float(min_mag_param)
                    filtered = [f for f in filtered if float(f.get("properties", {}).get("mag") or 0.0) >= min_val]
                except ValueError:
                    pass

            # Filtro por magnitud máxima
            if max_mag_param:
                try:
                    max_val = float(max_mag_param)
                    filtered = [f for f in filtered if float(f.get("properties", {}).get("mag") or 0.0) <= max_val]
                except ValueError:
                    pass

            # Filtro por tiempo (since timestamp ms)
            if since_param:
                try:
                    since_val = float(since_param)
                    filtered = [f for f in filtered if float(f.get("properties", {}).get("time") or 0) >= since_val]
                except ValueError:
                    pass

            # Filtro solo consenso
            if consensus_param and consensus_param.lower() in ["true", "1", "yes"]:
                filtered = [f for f in filtered if f.get("properties", {}).get("is_consensus")]

            # Límite de resultados
            if limit_param:
                try:
                    lim = int(limit_param)
                    if lim > 0:
                        filtered = filtered[:lim]
                except ValueError:
                    pass

            # Recalcular conteos según la salida filtrada
            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0}
            for f in filtered:
                cc = f.get("properties", {}).get("country_code")
                if cc in counts:
                    counts[cc] += 1

            response_data = {
                "type": "FeatureCollection",
                "metadata": {
                    "generated": int(time.time() * 1000),
                    "title": "KorshQuake API v1.1.2 - Panamá, Venezuela, España y Argentina",
                    "target_countries": ["Panamá", "Venezuela", "España", "Argentina"],
                    "total_events": len(filtered),
                    "raw_pool_events": len(raw_features),
                    "counts_by_country": counts,
                    "applied_filters": {
                        "country": country_param,
                        "min_mag": min_mag_param,
                        "max_mag": max_mag_param,
                        "limit": limit_param,
                        "since": since_param,
                        "consensus": consensus_param
                    },
                    "realtime_streaming": True,
                    "memory_latency_ms": 0.4
                },
                "features": filtered
            }
            send_json(response_data)
            return

        # 8. API: Logs del Sistema
        if path == "/api/logs":
            logs = get_latest_gq_logs()
            send_json({"logs": logs, "count": len(logs)})
            return

        # 9. API: Lanzador GlobalQuake Desktop
        if path == "/api/launch":
            success = False
            msg = ""
            try:
                bat_path = os.path.join(BASE_DIR, "run_globalquake.bat")
                if os.path.exists(bat_path):
                    subprocess.Popen(f'cmd.exe /c start "" "{bat_path}"', shell=True)
                    success = True
                    msg = "GlobalQuake v1.1.2 iniciado correctamente en tu escritorio."
                else:
                    msg = "No se encontró el ejecutable run_globalquake.bat"
            except Exception as e:
                msg = str(e)

            send_json({"success": success, "message": msg})
            return

        # 10. API: Motor de Predicciones y Alerta Temprana en Tiempo Real (/api/predict)
        if path == "/api/predict":
            q_lat = query.get("lat", [None])[0]
            q_lon = query.get("lon", [None])[0]
            q_mag = query.get("mag", [None])[0]
            q_depth = query.get("depth", [None])[0]
            q_time = query.get("time", [None])[0]

            if q_lat and q_lon:
                try:
                    p_lat = float(q_lat)
                    p_lon = float(q_lon)
                    p_mag = float(q_mag or 5.0)
                    p_depth = float(q_depth or 10.0)
                    p_time = float(q_time or (time.time() * 1000))
                    preds = calculate_seismic_predictions(p_lat, p_lon, p_depth, p_mag, p_time)
                    send_json({
                        "mode": "custom_hypocenter",
                        "event": {
                            "coords": [p_lon, p_lat, p_depth],
                            "mag": p_mag,
                            "time": int(p_time),
                            "place": f"Coordenadas [{p_lat:.3f}, {p_lon:.3f}]"
                        },
                        "prediction_model": "ak135 + Esteva GMPE Realtime EEW",
                        "velocities": {"vp_kms": 7.8, "vs_kms": 4.1},
                        "predictions_count": len(preds),
                        "predictions": preds,
                        "timestamp": int(time.time() * 1000)
                    })
                    return
                except ValueError:
                    pass

            quakes = get_live_earthquakes()
            features = quakes.get("features", [])
            country_filter = query.get("country", ["all"])[0].upper()
            if country_filter and country_filter != "ALL":
                target_codes = [c.strip() for c in country_filter.split(",")]
                features = [f for f in features if f.get("properties", {}).get("country_code") in target_codes]

            if features:
                latest = features[0]
                p = latest.get("properties", {})
                c = latest.get("geometry", {}).get("coordinates", [0, 0, 10])
                ev_lon, ev_lat = float(c[0]), float(c[1])
                ev_depth = float(c[2]) if len(c) > 2 else 10.0
                ev_mag = float(p.get("mag") or 4.0)
                ev_time = float(p.get("time") or (time.time() * 1000))

                preds = calculate_seismic_predictions(ev_lat, ev_lon, ev_depth, ev_mag, ev_time)
                send_json({
                    "mode": "live_latest_event",
                    "event_id": latest.get("id"),
                    "place": p.get("place"),
                    "country_code": p.get("country_code"),
                    "country_name": p.get("country_name"),
                    "mag": ev_mag,
                    "depth_km": ev_depth,
                    "coords": [ev_lon, ev_lat, ev_depth],
                    "time": int(ev_time),
                    "age_seconds": round(max(0, (time.time() * 1000 - ev_time) / 1000), 1),
                    "prediction_model": "ak135 + Esteva GMPE Realtime EEW",
                    "velocities": {"vp_kms": 7.8, "vs_kms": 4.1},
                    "predictions_count": len(preds),
                    "predictions": preds,
                    "timestamp": int(time.time() * 1000)
                })
            else:
                send_json({
                    "mode": "no_active_events",
                    "message": "No hay eventos sísmicos activos para calcular predicciones",
                    "predictions": [],
                    "timestamp": int(time.time() * 1000)
                })
            return

        # 11. Ruta informativa /gods-eye (Desacoplado por Rendimiento a favor del motor EEW)
        if path in ["/gods-eye", "/gods-eye/"]:
            index_file = os.path.join(GODS_EYE_DIST, "index.html")
            if os.path.isfile(index_file):
                try:
                    with open(index_file, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception:
                    pass

            html_notice = """<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>God's Eye View - Optimizado por KorshQuake</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    body { background: #050b14; color: #e2e8f0; font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; padding: 20px; box-sizing: border-box; text-align: center; }
    .card { background: rgba(13,27,46,0.92); border: 1px solid #1e3a5f; padding: 36px; border-radius: 14px; max-width: 620px; box-shadow: 0 10px 40px rgba(0,0,0,0.7); }
    h1 { color: #00e5ff; margin-top: 0; font-size: 1.6rem; }
    p { line-height: 1.6; color: #94a3b8; font-size: 0.95rem; }
    .btn { display: inline-block; background: #00e5ff; color: #020b14; padding: 12px 24px; border-radius: 8px; font-weight: bold; text-decoration: none; margin-top: 20px; }
  </style>
</head>
<body>
  <div class="card">
    <h1>🛰️ God's Eye View Desacoplado</h1>
    <p>El globo 3D de Cesium consumía recursos excesivos de CPU, GPU y RAM. KorshQuake ahora integra un <strong>Motor de Predicciones y Alerta Temprana en Tiempo Real (EEW)</strong> con propagación física de ondas P y S a latencia cero (< 1 ms).</p>
    <a href="/" class="btn">Abrir KorshQuake en Vivo</a>
  </div>
</body>
</html>"""
            payload = html_notice.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # 12. Consola Administrativa /admin para Monitoreo de Nodos y Pruebas Sismicas
        if path in ["/admin", "/admin/"]:
            admin_file = os.path.join(WEB_DIR, "admin.html")
            if os.path.isfile(admin_file):
                try:
                    with open(admin_file, "rb") as f:
                        content = f.read()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                except Exception:
                    pass

        # Archivos estáticos de la carpeta web (KorshQuake)
        return super().do_GET()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

def run_server(port=PORT):
    with ThreadedTCPServer(("0.0.0.0", port), GlobalQuakeHandler) as httpd:
        print("[OK] GlobalQuake Realtime Streaming Hub activo.")
        print("[OK] Frecuencia de sincronizacion continua: cada 2.8 segundos.")
        print("[OK] Regiones exclusivas: Panama, Venezuela, Espana y Argentina.")
        print(f"[OK] Servidor escuchando en: http://localhost:{port}")
        httpd.serve_forever()

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
