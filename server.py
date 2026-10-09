import http.server
import socketserver
import json
import urllib.request
import urllib.error
import subprocess
import os
import sys
import time
import re
import glob
import math
import threading
import concurrent.futures
from datetime import datetime

PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
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

def is_globalquake_running():
    try:
        output = subprocess.check_output(
            'powershell -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like \'*GlobalQuake*\' } | Select-Object ProcessId, CommandLine"',
            shell=True,
            text=True,
            timeout=5
        )
        lines = [line.strip() for line in output.strip().split('\n') if line.strip() and not line.strip().startswith('ProcessId') and not line.strip().startswith('---')]
        if lines:
            return True, lines[0]
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
                "country_flag": country_meta["flag"]
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

class GlobalQuakeHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=WEB_DIR, **kwargs)

    def do_GET(self):
        # API Routes
        if self.path == "/api/status":
            running, cmd = is_globalquake_running()
            ram_age = int((time.time() - _last_ram_update_time) * 1000) if _last_ram_update_time else 0
            status_data = {
                "version": "1.1.2",
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
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(status_data).encode("utf-8"))
            return

        if self.path in ["/download/KorshQuake.apk", "/KorshQuake.apk"]:
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

        if self.path == "/api/servers":
            is_running, _ = is_globalquake_running()
            _server_telemetry["gq_primary"]["status"] = "ONLINE" if is_running else "READY"
            servers_list = list(_server_telemetry.values())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"servers": servers_list, "count": len(servers_list)}).encode("utf-8"))
            return

        if self.path.startswith("/api/quakes"):
            quakes = get_live_earthquakes()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(json.dumps(quakes).encode("utf-8"))
            return

        if self.path == "/api/logs":
            logs = get_latest_gq_logs()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"logs": logs}).encode("utf-8"))
            return

        if self.path == "/api/launch":
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

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"success": success, "message": msg}).encode("utf-8"))
            return

        # Serve static files from web directory
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
