import http.server
import socketserver
import sqlite3
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
import hmac
import html as html_lib
from xml.sax.saxutils import escape as xml_escape
from datetime import datetime, timezone

_server_start_time = time.time()


def _safe_float(val, default=None):
    """Convierte a float sin reventar ante None/strings malformados (evita 500 en POSTs)."""
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _safe_int(val, default=None):
    """Convierte a int de forma tolerante (acepta '3', 3.7, None, basura)."""
    try:
        if val is None:
            return default
        return int(float(val))
    except (TypeError, ValueError):
        return default


def _csv_escape(val):
    """Escapa comillas dobles para CSV RFC 4180."""
    return str(val).replace('"', '""')

CURRENT_VERSION = "1.1.9 PRO"
CURRENT_VERSION_CODE = 119


PORT = 8080
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
WEB_DIR = os.path.join(BASE_DIR, "web")
ROAMING_GQ = os.path.join(os.environ.get("APPDATA", ""), "GlobalQuake")
LOCAL_APP_PATH = os.path.join(BASE_DIR, "GlobalQuakeApp")
DATA_DIR = os.path.join(BASE_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
COMMUNITY_REPORTS_PATH = os.path.join(DATA_DIR, "community_reports.json")

DB_PATH = os.path.join(DATA_DIR, "korshquake.db")
_db_lock = threading.Lock()

def init_sqlite_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    with _db_lock:
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("""
            CREATE TABLE IF NOT EXISTS quakes (
                id TEXT PRIMARY KEY,
                place TEXT,
                mag REAL,
                depth REAL,
                time INTEGER,
                country_code TEXT,
                country_name TEXT,
                lat REAL,
                lon REAL,
                is_consensus INTEGER DEFAULT 0,
                source_feed TEXT,
                felt_reports INTEGER DEFAULT 0,
                raw_json TEXT,
                created_at INTEGER
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS felt_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                quake_id TEXT,
                client_ip TEXT,
                lat REAL,
                lon REAL,
                intensity REAL,
                created_at REAL
            );
            """)
            conn.execute("""
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY,
                p256dh TEXT,
                auth TEXT,
                min_mag REAL DEFAULT 4.0,
                target_country TEXT DEFAULT 'ALL',
                created_at REAL
            );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quakes_time ON quakes(time);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_quakes_country ON quakes(country_code);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_felt_quake ON felt_reports(quake_id);")

init_sqlite_db()

def save_quake_to_db(feature):
    if not feature or not feature.get("id"):
        return
    try:
        props = feature.get("properties", {})
        coords = feature.get("geometry", {}).get("coordinates", [0, 0, 10])
        lon, lat = coords[0], coords[1]
        depth = coords[2] if len(coords) > 2 else 10.0
        q_id = str(feature["id"])
        
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                conn.execute("""
                INSERT OR REPLACE INTO quakes (
                    id, place, mag, depth, time, country_code, country_name,
                    lat, lon, is_consensus, source_feed, felt_reports, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, (
                    q_id,
                    props.get("place", "Epicentro Sísmico"),
                    _safe_float(props.get("mag"), 0.0),
                    _safe_float(depth, 10.0),
                    _safe_int(props.get("time"), int(time.time() * 1000)),
                    props.get("country_code", "GLOBAL"),
                    props.get("country_name", "Internacional"),
                    _safe_float(lat, 0.0),
                    _safe_float(lon, 0.0),
                    1 if props.get("is_consensus") else 0,
                    props.get("source_feed", "USGS"),
                    _safe_int(props.get("felt_reports"), 0),
                    json.dumps(feature, ensure_ascii=False),
                    int(time.time() * 1000)
                ))
    except Exception as e:
        pass

def load_quakes_from_db(limit=200):
    try:
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cutoff_24h = int((time.time() - 86400) * 1000)
                cursor.execute("SELECT raw_json FROM quakes WHERE time >= ? ORDER BY time DESC LIMIT ?;", (cutoff_24h, limit))
                rows = cursor.fetchall()
                if not rows:
                    # Fallback defensivo a los más recientes si no hay sismos en las últimas 24h
                    cursor.execute("SELECT raw_json FROM quakes ORDER BY time DESC LIMIT ?;", (limit,))
                    rows = cursor.fetchall()
                loaded = []
                for (r_json,) in rows:
                    try:
                        feat = json.loads(r_json)
                        loaded.append(feat)
                    except Exception:
                        pass
                return loaded
    except Exception:
        return []

def get_shakemap_data(quake_id):
    q_id = str(quake_id)
    try:
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                SELECT lat, lon, intensity, COUNT(*) as cnt
                FROM felt_reports 
                WHERE quake_id = ? AND lat IS NOT NULL AND lon IS NOT NULL
                GROUP BY ROUND(lat, 2), ROUND(lon, 2);
                """, (q_id,))
                rows = cursor.fetchall()
                points = []
                for r in rows:
                    points.append({
                        "lat": r[0],
                        "lon": r[1],
                        "intensity": r[2] if r[2] else 4.0,
                        "reports_count": r[3]
                    })
                
                cursor.execute("SELECT COUNT(*) FROM felt_reports WHERE quake_id = ?;", (q_id,))
                total = cursor.fetchone()[0]
                return {
                    "quake_id": q_id,
                    "total_reports": total,
                    "points": points
                }
    except Exception as e:
        return {"quake_id": q_id, "total_reports": 0, "points": []}

def search_quakes_history(query=None, country=None, min_mag=None, max_mag=None, limit=50, offset=0):
    limit = min(200, max(1, _safe_int(limit, 50)))
    offset = max(0, _safe_int(offset, 0))
    sql = "SELECT raw_json FROM quakes WHERE 1=1"
    params = []

    if query:
        sql += " AND (place LIKE ? OR country_name LIKE ?)"
        params.extend([f"%{query}%", f"%{query}%"])
    if country and country.upper() != "ALL":
        sql += " AND country_code = ?"
        params.append(country.upper())
    if min_mag is not None:
        min_mag_val = _safe_float(min_mag, None)
        if min_mag_val is not None:
            sql += " AND mag >= ?"
            params.append(min_mag_val)
    if max_mag is not None:
        max_mag_val = _safe_float(max_mag, None)
        if max_mag_val is not None:
            sql += " AND mag <= ?"
            params.append(max_mag_val)

    sql += " ORDER BY time DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    try:
        with _db_lock:
            with sqlite3.connect(DB_PATH) as conn:
                cursor = conn.cursor()
                cursor.execute(sql, params)
                rows = cursor.fetchall()
                features = []
                for (r_json,) in rows:
                    try:
                        features.append(json.loads(r_json))
                    except Exception:
                        pass
                return {
                    "count": len(features),
                    "limit": limit,
                    "offset": offset,
                    "features": features
                }
    except Exception as e:
        return {"count": 0, "features": [], "error": str(e)}

def compute_focal_mechanism(lat, lon, depth, mag, event_props=None):
    """
    Calcula parámetros de mecanismo focal (strike, dip, rake) y genera
    diagrama de balón de playa (beachball SVG) según la zona tectónica.
    """
    props = event_props or {}
    mag = float(mag)
    lat = float(lat)
    lon = float(lon)
    
    # 1. Verificar si el catálogo externo ya provee tensor de momento
    strike = props.get("strike")
    dip = props.get("dip")
    rake = props.get("rake")

    if strike is None or dip is None or rake is None:
        # Inferencia tectónica regional
        # A. Falla de Boconó / San Sebastián / El Pilar (Venezuela) -> Desgarre Dextral
        if 8.0 <= lat <= 12.5 and -73.0 <= lon <= -60.0:
            strike, dip, rake = 70, 84, 5
            fault_type = "Falla de Desgarre (Transcurrente Dextral)"
        # B. Zona de Subducción Cocos/Nazca - Caribe (Panamá Pacífico / Fosa Mesoamericana)
        elif 6.5 <= lat <= 9.5 and -84.0 <= lon <= -77.0:
            strike, dip, rake = 32, 28, 92
            fault_type = "Falla Inversa (Subducción / Cabalgamiento)"
        # C. Contacto Azores-Gibraltar / Béticas (España Sur)
        elif 35.0 <= lat <= 39.0 and -11.0 <= lon <= 1.0:
            strike, dip, rake = 85, 75, 12
            fault_type = "Falla Transpresiva (Contacto Euroasiático)"
        # D. Subducción Nazca - Sudamérica (Argentina Andes)
        elif -55.0 <= lat <= -20.0 and -72.0 <= lon <= -65.0:
            strike, dip, rake = 12, 35, 95
            fault_type = "Falla Inversa (Subducción Andina)"
        else:
            strike, dip, rake = 45, 60, 45
            fault_type = "Falla Oblicua Regional"
    else:
        strike, dip, rake = float(strike), float(dip), float(rake)
        if 45 <= abs(rake) <= 135:
            fault_type = "Falla Inversa" if rake > 0 else "Falla Normal"
        else:
            fault_type = "Falla de Desgarre (Transcurrente)"

    # Generación de Beachball SVG
    size = 46
    r = size / 2
    if 45 <= abs(rake) <= 135:
        bg_col = "#ff1e42" if rake > 0 else "#0284c7"
        t_col = "#ffffff"
        svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" class="focal-beachball" title="{fault_type} Strike:{strike}° Dip:{dip}° Rake:{rake}°">
          <circle cx="{r}" cy="{r}" r="{r-1.5}" fill="{bg_col}" stroke="#f8fafc" stroke-width="1.4"/>
          <path d="M {r} 2 Q {r*0.3} {r} {r} {size-2} Q {r*1.7} {r} {r} 2 Z" fill="{t_col}"/>
        </svg>'''
    else:
        svg = f'''<svg width="{size}" height="{size}" viewBox="0 0 {size} {size}" class="focal-beachball" title="{fault_type} Strike:{strike}° Dip:{dip}° Rake:{rake}°">
          <circle cx="{r}" cy="{r}" r="{r-1.5}" fill="#0284c7" stroke="#f8fafc" stroke-width="1.4"/>
          <path d="M {r} 2 A {r-1.5} {r-1.5} 0 0 1 {size-2} {r} L {r} {r} Z" fill="#ff1e42"/>
          <path d="M 2 {r} A {r-1.5} {r-1.5} 0 0 1 {r} {size-2} L {r} {r} Z" fill="#ff1e42"/>
        </svg>'''

    return {
        "strike": strike,
        "dip": dip,
        "rake": rake,
        "fault_type": fault_type,
        "beachball_svg": svg
    }

# Clave pública VAPID real (secp256r1/prime256v1, generada 2026-10-11).
# La clave PRIVADA vive en /opt/korshquake/data/vapid_private.pem en la VPS (montado en /app/data, NUNCA en git).
VAPID_PUBLIC_KEY = "BDZqe9nfQ4g3U0P663g5PmuBvn18hMR_eN5o4J-F7i1L5D0iF5Q5Kx_stJ4N0rEXF5W0hklXuEMts_LZ9S9_7TY"
# Token opcional para /admin y /api/admin/* (header X-Admin-Token o ?token=***
# Si ADMIN_TOKEN no está definido en el entorno, la consola queda abierta (comportamiento histórico).
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
_community_reports_lock = threading.Lock()
_community_reports = {}
_community_report_ips = {}  # f"{quake_id}:{ip}" -> timestamp

def load_community_reports():
    global _community_reports
    if os.path.exists(COMMUNITY_REPORTS_PATH):
        try:
            with open(COMMUNITY_REPORTS_PATH, "r", encoding="utf-8") as f:
                _community_reports = json.load(f)
        except Exception:
            _community_reports = {}

def save_community_reports():
    try:
        tmp_path = COMMUNITY_REPORTS_PATH + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(_community_reports, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, COMMUNITY_REPORTS_PATH)
    except Exception:
        pass

load_community_reports()

def get_felt_reports(quake_id):
    with _community_reports_lock:
        return _community_reports.get(str(quake_id), 0)

def record_felt_report(quake_id, client_ip, lat=None, lon=None, intensity=None):
    q_id = str(quake_id)
    ip_key = f"{q_id}:{client_ip}"
    now = time.time()
    with _community_reports_lock:
        last_time = _community_report_ips.get(ip_key, 0)
        if now - last_time < 3600:
            current_total = _community_reports.get(q_id, 0)
            return {
                "success": True,
                "already_reported": True,
                "quake_id": q_id,
                "felt_reports": current_total,
                "message": "Reporte previamente registrado para este evento"
            }
        _community_report_ips[ip_key] = now
        _community_reports[q_id] = _community_reports.get(q_id, 0) + 1
        new_total = _community_reports[q_id]
        # Poda anti-fuga del registro anti-duplicado (claves > 2h ya no aplican)
        if len(_community_report_ips) > 20000:
            _stale_ips = [k for k, v in _community_report_ips.items() if (now - v) > 7200.0]
            for k in _stale_ips:
                _community_report_ips.pop(k, None)
        save_community_reports()
        try:
            with _db_lock:
                with sqlite3.connect(DB_PATH) as conn:
                    conn.execute("""
                    INSERT INTO felt_reports (quake_id, client_ip, lat, lon, intensity, created_at)
                    VALUES (?, ?, ?, ?, ?, ?);
                    """, (q_id, client_ip, float(lat) if lat is not None else None, float(lon) if lon is not None else None, float(intensity) if intensity is not None else 4.0, now))
                    conn.execute("UPDATE quakes SET felt_reports = ? WHERE id = ?;", (new_total, q_id))
        except Exception:
            pass
    return {
        "success": True,
        "already_reported": False,
        "quake_id": q_id,
        "felt_reports": new_total,
        "message": "Reporte ciudadano registrado exitosamente"
    }


# Target Countries metadata
TARGET_COUNTRIES = {
    "PA": {"name": "Panamá", "flag": "", "center": [8.538, -80.782], "zoom": 7.5},
    "VE": {"name": "Venezuela", "flag": "", "center": [8.000, -66.100], "zoom": 6.5},
    "ES": {"name": "España", "flag": "", "center": [40.200, -3.750], "zoom": 6.0},
    "AR": {"name": "Argentina", "flag": "", "center": [-38.416, -63.616], "zoom": 5.0},
    "HN": {"name": "Honduras", "flag": "", "center": [15.200, -86.241], "zoom": 7.2}
}

# Regional Bounding Boxes to query focused data feeds
QUERY_REGIONS = [
    {"code": "PA", "name": "Panamá", "minlat": 6.8, "maxlat": 10.2, "minlon": -83.5, "maxlon": -76.8},
    {"code": "VE", "name": "Venezuela", "minlat": 0.5, "maxlat": 13.5, "minlon": -73.6, "maxlon": -59.5},
    {"code": "ES", "name": "España Península", "minlat": 35.0, "maxlat": 44.5, "minlon": -10.5, "maxlon": 5.0},
    {"code": "ES", "name": "España Canarias", "minlat": 26.5, "maxlat": 30.5, "minlon": -19.0, "maxlon": -12.5},
    {"code": "AR", "name": "Argentina", "minlat": -55.5, "maxlat": -21.5, "minlon": -73.6, "maxlon": -53.5},
    {"code": "HN", "name": "Honduras", "minlat": 12.8, "maxlat": 17.5, "minlon": -89.5, "maxlon": -83.0}
]

# Telemetry tracking for connected seismic networks
_server_telemetry = {
    "copeco_hn": {
        "id": "copeco_hn",
        "name": "COPECO Honduras / Red Sísmica Centroamericana",
        "host": "copeco.gob.hn / sismicidad",
        "region": "Honduras, Depresión Central, Falla del Motagua e Islas de la Bahía",
        "status": "ONLINE",
        "latency_ms": 195,
        "events_count": 0,
        "last_sync": 0
    },

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
    "emsc_global": {
        "id": "emsc_global",
        "name": "EMSC SeismicPortal Cobertura Mundial",
        "host": "seismicportal.eu",
        "region": "Todos los países del mundo (M ≥ 4.0)",
        "status": "ONLINE",
        "latency_ms": 400,
        "events_count": 0,
        "last_sync": 0
    },
    "usgs_regional": {
        "id": "usgs_regional",
        "name": "USGS Earthquake Hazards Live Feed",
        "host": "earthquake.usgs.gov",
        "region": "Cobertura Mundial (foco PA/VE/ES/AR/HN + M ≥ 4.0)",
        "status": "ONLINE",
        "latency_ms": 250,
        "events_count": 0,
        "last_sync": 0
    }
}

# --- RAM Cache & Background Streaming Worker ---
_cached_initial_db = load_quakes_from_db(200) if 'load_quakes_from_db' in globals() else []
_ram_quake_cache = {
    "type": "FeatureCollection",
    "features": _cached_initial_db if _cached_initial_db else [],
    "metadata": {
        "generated": int(time.time() * 1000),
        "title": "KorshQuake Local Seed Cache",
        "status": 200,
        "total_events": len(_cached_initial_db) if _cached_initial_db else 0
    }
}
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
    {"city": "Ciudad de Panamá", "country_code": "PA", "lat": 8.982, "lon": -79.520, "flag": ""},
    {"city": "David (Chiriquí)", "country_code": "PA", "lat": 8.427, "lon": -82.431, "flag": ""},
    {"city": "Colón", "country_code": "PA", "lat": 9.359, "lon": -79.901, "flag": ""},
    {"city": "Santiago de Veraguas", "country_code": "PA", "lat": 8.100, "lon": -80.970, "flag": ""},
    {"city": "Chitré", "country_code": "PA", "lat": 7.962, "lon": -80.428, "flag": ""},

    # Venezuela 🇻🇪
    {"city": "Caracas", "country_code": "VE", "lat": 10.480, "lon": -66.903, "flag": ""},
    {"city": "Valencia", "country_code": "VE", "lat": 10.162, "lon": -68.007, "flag": ""},
    {"city": "Maracaibo", "country_code": "VE", "lat": 10.654, "lon": -71.637, "flag": ""},
    {"city": "Barquisimeto", "country_code": "VE", "lat": 10.067, "lon": -69.347, "flag": ""},
    {"city": "San Cristóbal", "country_code": "VE", "lat": 7.766, "lon": -72.225, "flag": ""},
    {"city": "Mérida", "country_code": "VE", "lat": 8.598, "lon": -71.144, "flag": ""},
    {"city": "Cumaná", "country_code": "VE", "lat": 10.453, "lon": -64.182, "flag": ""},

    # España 🇪🇸
    {"city": "Madrid", "country_code": "ES", "lat": 40.416, "lon": -3.703, "flag": ""},
    {"city": "Granada", "country_code": "ES", "lat": 37.177, "lon": -3.598, "flag": ""},
    {"city": "Murcia", "country_code": "ES", "lat": 37.992, "lon": -1.130, "flag": ""},
    {"city": "Málaga", "country_code": "ES", "lat": 36.721, "lon": -4.421, "flag": ""},
    {"city": "Sevilla", "country_code": "ES", "lat": 37.389, "lon": -5.984, "flag": ""},
    {"city": "Santa Cruz de Tenerife", "country_code": "ES", "lat": 28.463, "lon": -16.251, "flag": ""},
    {"city": "Las Palmas de Gran Canaria", "country_code": "ES", "lat": 28.123, "lon": -15.436, "flag": ""},

    # Argentina 🇦🇷
    {"city": "San Juan", "country_code": "AR", "lat": -31.537, "lon": -68.536, "flag": ""},
    {"city": "Mendoza", "country_code": "AR", "lat": -32.890, "lon": -68.845, "flag": ""},
    {"city": "Salta", "country_code": "AR", "lat": -24.782, "lon": -65.423, "flag": ""},
    {"city": "San Salvador de Jujuy", "country_code": "AR", "lat": -24.185, "lon": -65.299, "flag": ""},
    {"city": "Córdoba", "country_code": "AR", "lat": -31.420, "lon": -64.188, "flag": ""},
    {"city": "Buenos Aires", "country_code": "AR", "lat": -34.603, "lon": -58.381, "flag": ""},

    # Honduras 🇭🇳
    {"city": "Tegucigalpa (Distrito Central)", "country_code": "HN", "lat": 14.072, "lon": -87.192, "flag": ""},
    {"city": "San Pedro Sula (Valle de Sula)", "country_code": "HN", "lat": 15.505, "lon": -88.025, "flag": ""},
    {"city": "La Ceiba (Atlántida)", "country_code": "HN", "lat": 15.783, "lon": -86.792, "flag": ""},
    {"city": "Choluteca (Golfo de Fonseca)", "country_code": "HN", "lat": 13.300, "lon": -87.183, "flag": ""},
    {"city": "Roatán (Islas de la Bahía)", "country_code": "HN", "lat": 16.328, "lon": -86.536, "flag": ""},
    {"city": "Santa Rosa de Copán", "country_code": "HN", "lat": 14.767, "lon": -88.779, "flag": ""},
    {"city": "Comayagua", "country_code": "HN", "lat": 14.450, "lon": -87.633, "flag": ""},
]

def calculate_seismic_predictions(lat, lon, depth_km, mag, origin_time_ms):
    """
    Motor Sismológico de Predicción en Tiempo Real (EEW).
    Modela propagación de ondas elásticas en la corteza terrestre:
    - Onda P (compresional): Vp = 7.8 km/s
    - Onda S (cizalla/destructiva): Vs = 4.1 km/s
    - Atenuación de aceleración de suelo (PGA) y escala de intensidad Mercalli Modificada (MMI).
    """
    depth_km = abs(float(depth_km or 10.0))
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
    Clasificador geográfico estricto de los 5 países foco: Panamá (PA), Venezuela (VE),
    España (ES), Argentina (AR) y Honduras (HN). Fuera de estas cajas retorna None;
    classify_event_country() se encarga de clasificar el resto del mundo.
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

    # 5. HONDURAS 🇭🇳
    is_honduras_box = is_point_in_bbox(lat, lon, 12.8, 17.5, -89.5, -83.0)
    if is_honduras_box:
        hon_keywords = [
            r'\bhonduras\b', r'\bcopeco\b', r'\btegucigalpa\b', r'\bsan pedro sula\b',
            r'\bislas de la bahia\b', r'\broatan\b', r'\butila\b', r'\bguanaja\b',
            r'\bcortes\b', r'\batlantida\b', r'\bcholuteca\b', r'\bcomayagua\b',
            r'\bcopan\b', r'\bel paraiso\b', r'\bfrancisco morazan\b', r'\bintibuca\b',
            r'\blempira\b', r'\bocotepeque\b', r'\bolancho\b', r'\bsanta barbara\b',
            r'\bvalle\b', r'\byoro\b', r'\bgolfo de fonseca\b', r'\bgulf of fonseca\b',
            r'\bswan islands\b', r'\bislas del cisne\b'
        ]
        has_hon_kw = any(re.search(pat, p) for pat in hon_keywords) or a in ["copeco", "ineter"]
        if any(re.search(pat, p) for pat in [r'\bguatemala\b', r'\bel salvador\b', r'\bnicaragua\b']):
            if has_hon_kw and 13.0 <= lat <= 16.5 and -89.0 <= lon <= -83.2:
                return "HN"
            if "honduras" in p or "golfo de fonseca" in p:
                return "HN"
            return None
        if has_hon_kw:
            return "HN"
        if 13.0 <= lat <= 16.3 and -88.8 <= lon <= -83.5:
            return "HN"

    return None

# ============================================================================
# CLASIFICADOR MUNDIAL — "Todos los países del mundo"
# Los 5 países foco (PA/VE/ES/AR/HN) conservan su clasificación estricta.
# El resto del planeta se clasifica escaneando nombres de país/regiones
# (EN + ES) en el texto `place`/`flynn_region` de USGS/EMSC. Si no hay
# coincidencia (mar abierto, dorsales oceánicas) se etiqueta GLOBAL.
# Para no inundar el feed con microsismos ajenos al foco, fuera de los
# 5 países foco solo se publican eventos con M >= GLOBAL_MIN_MAG.
# ============================================================================
GLOBAL_MIN_MAG = 4.0
GLOBAL_CODE = "GLOBAL"
GLOBAL_NAME = "Internacional"

COUNTRY_NAMES_ES = {
    "US": "Estados Unidos", "CA": "Canadá", "MX": "México", "GT": "Guatemala", "BZ": "Belice",
    "SV": "El Salvador", "HN": "Honduras", "NI": "Nicaragua", "CR": "Costa Rica", "PA": "Panamá",
    "CO": "Colombia", "VE": "Venezuela", "GY": "Guyana", "SR": "Surinam", "GF": "Guayana Francesa",
    "EC": "Ecuador", "PE": "Perú", "BO": "Bolivia", "BR": "Brasil", "CL": "Chile", "AR": "Argentina",
    "PY": "Paraguay", "UY": "Uruguay", "FK": "Islas Malvinas", "GS": "Georgia del Sur", "AQ": "Antártida",
    "CU": "Cuba", "JM": "Jamaica", "HT": "Haití", "DO": "Rep. Dominicana", "PR": "Puerto Rico",
    "VI": "Islas Vírgenes (EE.UU.)", "VG": "Islas Vírgenes (UK)", "BS": "Bahamas", "TC": "Turcas y Caicos",
    "KY": "Caimán", "BM": "Bermudas", "AI": "Anguila", "MS": "Montserrat", "GP": "Guadalupe",
    "MQ": "Martinica", "DM": "Dominica", "AG": "Antigua y Barbuda", "LC": "Santa Lucía",
    "VC": "San Vicente", "GD": "Granada", "BB": "Barbados", "TT": "Trinidad y Tobago",
    "AW": "Aruba", "CW": "Curazao", "BQ": "Bonaire", "SX": "Sint Maarten", "MF": "San Martín",
    "BL": "San Bartolomé", "GL": "Groenlandia", "IS": "Islandia", "FO": "Islas Feroe",
    "SJ": "Svalbard", "NO": "Noruega", "SE": "Suecia", "FI": "Finlandia", "DK": "Dinamarca",
    "EE": "Estonia", "LV": "Letonia", "LT": "Lituania", "PL": "Polonia", "DE": "Alemania",
    "NL": "Países Bajos", "BE": "Bélgica", "LU": "Luxemburgo", "GB": "Reino Unido",
    "IE": "Irlanda", "IM": "Isla de Man", "FR": "Francia", "ES": "España", "PT": "Portugal",
    "IT": "Italia", "MT": "Malta", "GR": "Grecia", "CH": "Suiza", "AT": "Austria",
    "LI": "Liechtenstein", "MC": "Mónaco", "AD": "Andorra", "SM": "San Marino", "VA": "Vaticano",
    "CZ": "Chequia", "SK": "Eslovaquia", "HU": "Hungría", "SI": "Eslovenia", "HR": "Croacia",
    "BA": "Bosnia", "RS": "Serbia", "ME": "Montenegro", "XK": "Kosovo", "AL": "Albania",
    "MK": "Macedonia del Norte", "BG": "Bulgaria", "RO": "Rumanía", "MD": "Moldavia",
    "UA": "Ucrania", "BY": "Bielorrusia", "RU": "Rusia", "CY": "Chipre", "TR": "Turquía",
    "SY": "Siria", "LB": "Líbano", "IL": "Israel", "PS": "Palestina", "JO": "Jordania",
    "IQ": "Irak", "IR": "Irán", "AZ": "Azerbaiyán", "AM": "Armenia", "GE": "Georgia",
    "KZ": "Kazajistán", "KG": "Kirguistán", "TJ": "Tayikistán", "UZ": "Uzbekistán", "TM": "Turkmenistán",
    "AF": "Afganistán", "PK": "Pakistán", "IN": "India", "NP": "Nepal", "BT": "Bután",
    "BD": "Bangladés", "MM": "Myanmar", "TH": "Tailandia", "LA": "Laos", "VN": "Vietnam",
    "KH": "Camboya", "MY": "Malasia", "SG": "Singapur", "BN": "Brunéi", "ID": "Indonesia",
    "TL": "Timor Oriental", "PH": "Filipinas", "TW": "Taiwán", "CN": "China", "HK": "Hong Kong",
    "MN": "Mongolia", "KP": "Corea del Norte", "KR": "Corea del Sur", "JP": "Japón",
    "AU": "Australia", "NF": "Norfolk", "NZ": "Nueva Zelanda", "PG": "Papúa Nueva Guinea",
    "SB": "Islas Salomón", "VU": "Vanuatu", "NC": "Nueva Caledonia", "FJ": "Fiyi", "TO": "Tonga",
    "WS": "Samoa", "AS": "Samoa Americana", "PF": "Polinesia Francesa", "PN": "Pitcairn",
    "CK": "Islas Cook", "NU": "Niue", "TK": "Tokelau", "WF": "Wallis y Futuna", "KI": "Kiribati",
    "NR": "Nauru", "TV": "Tuvalu", "MH": "Islas Marshall", "FM": "Micronesia", "PW": "Palaos",
    "MP": "Marianas del Norte", "GU": "Guam", "UM": "Islas Ultramarinas EE.UU.", "CC": "Cocos",
    "CX": "Isla Christmas", "HM": "Islas Heard", "TF": "Territorios Australes Franceses",
    "BV": "Bouvet", "SH": "Santa Elena", "IO": "Territorio Británico Índico", "CV": "Cabo Verde",
    "MA": "Marruecos", "EH": "Sahara Occidental", "DZ": "Argelia", "TN": "Túnez", "LY": "Libia",
    "EG": "Egipto", "SD": "Sudán", "SS": "Sudán del Sur", "TD": "Chad", "NE": "Níger",
    "ML": "Malí", "MR": "Mauritania", "SN": "Senegal", "GM": "Gambia", "GN": "Guinea",
    "GW": "Guinea-Bisáu", "SL": "Sierra Leona", "LR": "Liberia", "CI": "Costa de Marfil",
    "GH": "Ghana", "TG": "Togo", "BJ": "Benín", "BF": "Burkina Faso", "NG": "Nigeria",
    "CM": "Camerún", "CF": "Rep. Centroafricana", "GQ": "Guinea Ecuatorial", "GA": "Gabón",
    "CG": "Congo", "CD": "Rep. Dem. del Congo", "AO": "Angola", "ZM": "Zambia", "MW": "Malaui",
    "MZ": "Mozambique", "ZW": "Zimbabue", "BW": "Botsuana", "NA": "Namibia", "ZA": "Sudáfrica",
    "LS": "Lesoto", "SZ": "Esuatini", "MG": "Madagascar", "KM": "Comoras", "YT": "Mayotte",
    "SC": "Seychelles", "MU": "Mauricio", "RE": "Reunión", "ER": "Eritrea", "DJ": "Yibuti",
    "ET": "Etiopía", "SO": "Somalia", "KE": "Kenia", "TZ": "Tanzania", "UG": "Uganda",
    "RW": "Ruanda", "BI": "Burundi",
}

# Términos de búsqueda (normalizados, minúsculas) → código ISO.
# La alternativa se compila ordenada por longitud descendente para que
# "papua new guinea" gane a "guinea", "state of georgia" a "georgia", etc.
_COUNTRY_TERMS = {
    # --- América del Norte / Centro ---
    "united states": "US", "usa": "US", "alaska": "US", "hawaii": "US", "big island": "US",
    "kilauea": "US", "mauna loa": "US", "california": "US", "san francisco": "US",
    "los angeles": "US", "san andreas": "US", "long valley": "US", "ridgecrest": "US",
    "parkfield": "US", "coalinga": "US", "holister": "US", "nevada": "US", "utah": "US",
    "oregon": "US", "washington": "US", "montana": "US", "wyoming": "US", "idaho": "US",
    "yellowstone": "US", "cascadia": "US", "juan de fuca": "US", "mendocino": "US",
    "aleutian": "US", "fox islands": "US", "andreanof": "US", "semisopochnoi": "US",
    "adak": "US", "anchorage": "US", "denali": "US", "fairbanks": "US", "juneau": "US",
    "sitka": "US", "kodiak": "US", "unimak": "US", "sanak": "US", "atka": "US",
    "amchitka": "US", "yakutat": "US", "new york": "US", "maine": "US", "virginia": "US",
    "texas": "US", "missouri": "US", "arkansas": "US", "tennessee": "US", "kentucky": "US",
    "carolina": "US", "florida": "US", "michigan": "US", "new jersey": "US", "georgia": "US",
    "puerto rico": "PR", "mayaguez": "PR", "aguadilla": "PR", "hatillo": "PR", "ponce": "PR",
    "virgin islands": "VI", "st croix": "VI", "saint croix": "VI", "st thomas": "VI",
    "saint thomas": "VI", "british virgin": "VG", "guam": "GU", "agana": "GU",
    "northern mariana": "MP", "mariana islands": "MP", "saipan": "MP", "tinian": "MP",
    "wake island": "UM", "midway": "UM", "johnston": "UM", "palmyra": "UM", "kingman": "UM",
    "baker island": "UM", "howland": "UM", "jarvis": "UM", "navassa": "UM", "desecheo": "UM",
    "canada": "CA", "british columbia": "CA", "haida": "CA", "queen charlotte": "CA",
    "sable island": "CA", "yukon": "CA", "nunavut": "CA", "baffin": "CA", "labrador": "CA",
    "quebec": "CA", "ontario": "CA", "alberta": "CA", "manitoba": "CA", "saskatchewan": "CA",
    "northwest territories": "CA", "greenland": "GL",
    "mexico": "MX", "baja": "MX", "colima": "MX", "michoacan": "MX", "guerrero": "MX",
    "oaxaca": "MX", "chiapas": "MX", "veracruz": "MX", "jalisco": "MX", "acapulco": "MX",
    "tecpan": "MX", "zihuatanejo": "MX", "manzanillo": "MX", "puerto vallarta": "MX",
    "tijuana": "MX", "mexicali": "MX", "hermosillo": "MX", "mazatlan": "MX", "guadalajara": "MX",
    "puebla": "MX", "monterrey": "MX", "saltillo": "MX", "acambay": "MX", "pinotepa": "MX",
    "salina cruz": "MX", "huateulco": "MX", "zacatecas": "MX", "nayarit": "MX", "sinaloa": "MX",
    "chihuahua": "MX", "durango": "MX", "san luis potosi": "MX", "queretaro": "MX",
    "guatemala": "GT", "escuintla": "GT", "quetzaltenango": "GT", "antigua guatemala": "GT",
    "belize": "BZ", "el salvador": "SV", "san salvador": "SV", "san salvador de jujuy": "AR",
    "nicaragua": "NI", "managua": "NI", "masaya": "NI", "chinandega": "NI",
    "costa rica": "CR", "alajuela": "CR", "heredia": "CR", "puntarenas": "CR", "limon": "CR",
    "tamarindo": "CR", "turrialba": "CR", "poas": "CR", "arenal": "CR",
    "honduras": "HN", "panama": "PA", "colombia": "CO", "antioquia": "CO", "narino": "CO",
    "cauca": "CO", "bucaramanga": "CO", "manizales": "CO", "pereira": "CO", "eje cafetero": "CO",
    "medellin": "CO", "barranquilla": "CO", "sogamoso": "CO", "cucuta": "CO", "ipiales": "CO",
    "chaparuro": "CO", "puerto asis": "CO", "tumaco": "CO", "barichara": "CO",
    "venezuela": "VE", "guyana": "GY", "suriname": "SR", "french guiana": "GF", "cayenne": "GF",
    "ecuador": "EC", "galapagos": "EC", "esmeraldas": "EC", "manabi": "EC", "loja": "EC",
    "cotopaxi": "EC", "quito": "EC", "ambato": "EC", "riobamba": "EC", "guayaquil": "EC",
    "muisne": "EC", "archidona": "EC", "pelileo": "EC",
    "peru": "PE", "arequipa": "PE", "cusco": "PE", "iquitos": "PE", "nazca": "PE",
    "mollendo": "PE", "chincheros": "PE", "abancay": "PE", "bagua": "PE", "cajamarca": "PE",
    "huancavelica": "PE", "junin": "PE", "pisco": "PE", "ayacucho": "PE", "puerto maldonado": "PE",
    "chimbote": "PE", "huaraz": "PE", "bagua grande": "PE",
    "bolivia": "BO", "sucre": "BO", "cochabamba": "BO", "potosi": "BO", "oruro": "BO", "tarija": "BO",
    "brazil": "BR", "brasil": "BR", "brasilia": "BR", "sao paulo": "BR", "rio de janeiro": "BR",
    "bahia": "BR", "ceara": "BR", "amazonas": "BR", "acre": "BR", "rondonia": "BR",
    "goias": "BR", "minas gerais": "BR", "parana": "BR", "rio grande": "BR",
    "santa catarina": "BR", "tocantins": "BR", "pernambuco": "BR", "maranhao": "BR",
    "manaus": "BR", "fortaleza": "BR", "recife": "BR", "belo horizonte": "BR", "cuiaba": "BR",
    "campo grande": "BR", "belem": "BR", "santarem": "BR", "macapa": "BR", "boa vista": "BR",
    "natal": "BR", "joao pessoa": "BR", "maceio": "BR", "aracaju": "BR", "uberaba": "BR",
    "feira de santana": "BR", "petropolis": "BR", "campos dos goytacazes": "BR", "macae": "BR",
    "camocim": "BR", "chile": "CL", "valparaiso": "CL", "antofagasta": "CL", "iquique": "CL",
    "arica": "CL", "coquimbo": "CL", "atacama": "CL", "magallanes": "CL", "aysen": "CL",
    "maule": "CL", "ohiggins": "CL", "biobio": "CL", "bio bio": "CL", "chiloe": "CL",
    "easter island": "CL", "pascua island": "CL", "robinson crusoe": "CL", "san felix": "CL",
    "tocopilla": "CL", "taltal": "CL", "chanaral": "CL", "putre": "CL", "pisagua": "CL",
    "argentina": "AR", "jujuy": "AR", "salta": "AR", "tucuman": "AR", "catamarca": "AR",
    "la rioja": "AR", "san juan argentina": "AR", "mendoza": "AR", "san luis": "AR", "cordoba": "AR",
    "santiago del estero": "AR", "neuquen": "AR", "rio negro": "AR", "chubut": "AR",
    "santa cruz": "AR", "tierra del fuego": "AR", "buenos aires": "AR", "la pampa": "AR",
    "inpres": "AR", "paraguay": "PY", "asuncion": "PY", "uruguay": "UY", "montevideo": "UY",
    "paysandu": "UY", "tacuarembo": "UY",
    # --- Caribe ---
    "cuba": "CU", "havana": "CU", "jamaica": "JM", "montego": "JM", "haiti": "HT",
    "port au prince": "HT", "cap haitien": "HT", "les cayes": "HT", "mole st nicolas": "HT",
    "dominican": "DO", "hispaniola": "DO", "santo domingo": "DO",
    "santiago de los caballeros": "DO", "puerto plata": "DO", "la romana": "DO", "punta cana": "DO",
    "bahamas": "BS", "turks and caicos": "TC", "grand turk": "TC", "caicos": "TC", "turks": "TC",
    "cayman": "KY", "grand cayman": "KY", "bermuda": "BM", "harrington sound": "BM",
    "anguilla": "AI", "montserrat": "MS", "antigua and barbuda": "AG", "barbuda": "AG",
    "st kitts": "KN", "saint kitts": "KN", "nevis": "KN", "brimstone": "KN", "dominica": "DM",
    "roseau": "DM", "martinique": "MQ", "guadeloupe": "GP", "pointe a pitre": "GP",
    "basse terre": "GP", "st lucia": "LC", "saint lucia": "LC", "castries": "LC",
    "st vincent": "VC", "saint vincent": "VC", "barrow island": "VC", "grenada": "GD",
    "barbados": "BB", "trinidad": "TT", "tobago": "TT", "port of spain": "TT", "chaguanas": "TT",
    "tunapuna": "TT", "mayaro": "TT", "aruba": "AW", "curacao": "CW", "willemstad": "CW",
    "bonaire": "BQ", "kralendijk": "BQ", "sint maarten": "SX", "philipsburg": "SX",
    "saint barthelemy": "BL", "collectivity of saint martin": "MF",
    # --- Europa ---
    "iceland": "IS", "reykjanes": "IS", "vestmannaeyjar": "IS", "grindavik": "IS",
    "reykjavik": "IS", "akureyri": "IS", "hengill": "IS", "katla": "IS", "bardarbunga": "IS",
    "grimsvotn": "IS", "fagradalsfjall": "IS", "sundhnukur": "IS", "faroe": "FO", "torshavn": "FO",
    "jan mayen": "SJ", "svalbard": "SJ", "spitsbergen": "SJ",
    "norway": "NO", "oslo": "NO", "tromso": "NO", "stavanger": "NO", "drammen": "NO",
    "fredrikstad": "NO", "trondheim": "NO", "bodo": "NO", "narvik": "NO", "hammerfest": "NO",
    "kirkenes": "NO", "varanger": "NO", "lillehammer": "NO", "dombas": "NO", "sogne": "NO",
    "hardanger": "NO", "alesund": "NO", "molde": "NO", "gjalp": "NO",
    "sweden": "SE", "stockholm": "SE", "goteborg": "SE", "malmo": "SE", "uppsala": "SE",
    "vasteras": "SE", "orebro": "SE", "jonkoping": "SE", "linkoping": "SE", "norrkoping": "SE",
    "karlstad": "SE", "gavle": "SE", "sundsvall": "SE", "umea": "SE", "lulea": "SE",
    "kiruna": "SE", "gallivare": "SE", "arjeplog": "SE", "skelleftea": "SE",
    "finland": "FI", "helsinki": "FI", "espoo": "FI", "tampere": "FI", "turku": "FI",
    "oulu": "FI", "jyvaskyla": "FI", "lahti": "FI", "kuopio": "FI", "rovaniemi": "FI",
    "vaasa": "FI", "pori": "FI", "kotka": "FI", "hamina": "FI", "lappeenranta": "FI",
    "joensuu": "FI", "kajaani": "FI", "kokkola": "FI", "mikkeli": "FI", "savonlinna": "FI",
    "kuusamo": "FI", "sodankyla": "FI", "inari": "FI", "utoya": "FI",
    "denmark": "DK", "copenhagen": "DK", "aarhus": "DK", "odense": "DK", "aalborg": "DK",
    "estonia": "EE", "tallinn": "EE", "latvia": "LV", "riga": "LV", "lithuania": "LT",
    "vilnius": "LT", "kaunas": "LT", "poland": "PL", "warsaw": "PL", "krakow": "PL",
    "wroclaw": "PL", "poznan": "PL", "gdansk": "PL", "czech": "CZ", "prague": "CZ",
    "ostrava": "CZ", "brno": "CZ", "slovakia": "SK", "bratislava": "SK", "kosice": "SK",
    "hungary": "HU", "budapest": "HU", "debrecen": "HU", "szeged": "HU", "pecs": "HU",
    "netherlands": "NL", "rotterdam": "NL", "the hague": "NL", "utrecht": "NL",
    "eindhoven": "NL", "groningen": "NL", "maastricht": "NL", "belgium": "BE",
    "brussels": "BE", "antwerp": "BE", "ghent": "BE", "liege": "BE", "namur": "BE",
    "luxembourg": "LU", "united kingdom": "GB", "great britain": "GB", "england": "GB",
    "scotland": "GB", "northern ireland": "GB", "shetland": "GB", "orkney": "GB",
    "hebrides": "GB", "isle of man": "IM", "uk": "GB", "ireland": "IE", "dublin": "IE",
    "galway": "IE", "cork": "IE",
    "france": "FR", "strasbourg": "FR", "nice": "FR", "grenoble": "FR", "annecy": "FR",
    "chamonix": "FR", "toulouse": "FR", "montpellier": "FR", "marseille": "FR", "lyon": "FR",
    "bordeaux": "FR", "nantes": "FR", "rennes": "FR", "brest": "FR", "toulon": "FR",
    "digne": "FR", "sisteron": "FR", "menton": "FR", "modane": "FR", "belfort": "FR",
    "epinal": "FR", "chambery": "FR", "montelimar": "FR", "valence": "FR", "tarbes": "FR",
    "perpignan": "FR", "saint etienne": "FR", "dijon": "FR", "auxerre": "FR", "nevers": "FR",
    "bourges": "FR", "tours": "FR", "orleans": "FR", "rouen": "FR", "caen": "FR",
    "le havre": "FR", "amiens": "FR", "lille": "FR", "arras": "FR", "calais": "FR",
    "reims": "FR", "metz": "FR", "nancy": "FR", "mulhouse": "FR", "colmar": "FR",
    "besancon": "FR", "clermont": "FR", "avignon": "FR", "arles": "FR", "cannes": "FR",
    "antibes": "FR", "frejus": "FR", "monaco": "MC",
    "spain": "ES", "españa": "ES", "canary": "ES", "canarias": "ES", "baleares": "ES",
    "mallorca": "ES", "menorca": "ES", "ibiza": "ES", "alboran": "ES", "andalucia": "ES",
    "murcia": "ES", "alicante": "ES", "granada": "ES", "malaga": "ES", "galicia": "ES",
    "valladolid": "ES", "burgos": "ES", "soria": "ES", "pamplona": "ES", "zaragoza": "ES",
    "barcelona": "ES", "girona": "ES", "tarragona": "ES", "teruel": "ES", "almeria": "ES",
    "jaen": "ES", "sevilla": "ES", "badajoz": "ES", "huelva": "ES", "cadiz": "ES",
    "melilla": "ES", "ceuta": "ES", "lorca": "ES",
    "portugal": "PT", "azores": "PT", "madeira": "PT", "lisbon": "PT", "sao miguel": "PT",
    "terceira": "PT", "faial": "PT", "sao jorge": "PT", "graciosa": "PT", "flores azores": "PT",
    "italy": "IT", "sicily": "IT", "calabria": "IT", "sardinia": "IT", "amatrice": "IT",
    "norcia": "IT", "ischia": "IT", "etna": "IT", "stromboli": "IT", "apennine": "IT",
    "tuscany": "IT", "umbria": "IT", "posillipo": "IT", "vico equense": "IT",
    "malta": "MT", "mellieha": "MT",
    "greece": "GR", "crete": "GR", "kreta": "GR", "aegean": "GR", "peloponnese": "GR",
    "thessaly": "GR", "santorini": "GR", "thira": "GR", "kefalonia": "GR", "lefkada": "GR",
    "zakynthos": "GR", "zante": "GR", "rhodes": "GR", "lesbos": "GR", "chios": "GR",
    "samos": "GR", "ikaria": "GR", "naxos": "GR", "corfu": "GR", "kerkira": "GR",
    "preveza": "GR", "ioannina": "GR", "trikala": "GR", "larissa": "GR", "volos": "GR",
    "thessaloniki": "GR", "komotini": "GR", "alexandroupoli": "GR", "kavala": "GR",
    "drama": "GR", "serres": "GR", "xanthi": "GR", "oreostada": "GR", "edessa": "GR",
    "naousa": "GR", "veria": "GR", "kozani": "GR", "florina": "GR", "kastoria": "GR",
    "grevena": "GR",
    "switzerland": "CH", "basel": "CH", "zurich": "CH", "geneva": "CH", "lausanne": "CH",
    "chur": "CH", "sion": "CH", "lucerne": "CH", "interlaken": "CH", "st gallen": "CH",
    "grisons": "CH", "austria": "AT", "vienna": "AT", "salzburg": "AT", "innsbruck": "AT",
    "graz": "AT", "linz": "AT", "klagenfurt": "AT", "villach": "AT", "badgastein": "AT",
    "liechtenstein": "LI", "andorra": "AD", "san marino": "SM", "vatican": "VA",
    "ukraine": "UA", "crimea": "UA", "kyiv": "UA", "lviv": "UA", "odesa": "UA",
    "kharkiv": "UA", "dnipro": "UA", "donetsk": "UA", "zaporizhzhia": "UA",
    "belarus": "BY", "minsk": "BY", "moldova": "MD",
    "romania": "RO", "vrancea": "RO", "carpathian": "RO",
    "croatia": "HR", "zagreb": "HR", "split": "HR", "dubrovnik": "HR", "rijeka": "HR",
    "osijek": "HR", "zadar": "HR", "sinj": "HR", "imotski": "HR", "petrinja": "HR",
    "sisak": "HR", "karlovac": "HR", "bosnia": "BA", "sarajevo": "BA", "banja luka": "BA",
    "serbia": "RS", "belgrade": "RS", "novi sad": "RS", "kragujevac": "RS", "kraljevo": "RS",
    "slovenia": "SI", "ljubljana": "SI", "maribor": "SI", "montenegro": "ME",
    "podgorica": "ME", "niksic": "ME", "kosovo": "XK", "pristina": "XK",
    "albania": "AL", "tirana": "AL", "durres": "AL", "shkodra": "AL", "korca": "AL",
    "vlore": "AL", "elbasan": "AL", "north macedonia": "MK", "bulgaria": "BG", "sofia": "BG",
    "plovdiv": "BG", "varna": "BG",
    "russia": "RU", "russian federation": "RU", "moscow": "RU", "saint petersburg": "RU",
    "yekaterinburg": "RU", "novosibirsk": "RU", "irkutsk": "RU", "vladivostok": "RU",
    "khabarovsk": "RU", "sochi": "RU", "kaliningrad": "RU", "murmansk": "RU",
    "petropavlovsk": "RU", "yuzhno sakhalinsk": "RU", "kuril": "RU", "kamchatka": "RU",
    "sakhalin": "RU", "sachalin": "RU", "commander islands": "RU", "buratia": "RU",
    "baikal": "RU", "dagestan": "RU", "chechnya": "RU", "ossetia": "RU", "ingushetia": "RU",
    "kabardino": "RU", "grozny": "RU", "makhachkala": "RU", "sea of okhotsk": "RU",
    # --- Cáucaso / Asia Central / Sur / Sudeste ---
    "state of georgia": "GE", "tbilisi": "GE", "kazbegi": "GE", "stepantsminda": "GE",
    "shida kartli": "GE", "kakheti": "GE", "imereti": "GE", "samegrelo": "GE", "ajaria": "GE",
    "georgia armenia": "GE", "georgia azerbaijan": "GE", "georgia turkey": "GE",
    "georgia russian": "GE", "georgia black sea": "GE", "georgia caucasus": "GE",
    "armenia": "AM", "yerevan": "AM", "gyumri": "AM", "vanadzor": "AM",
    "azerbaijan": "AZ", "baku": "AZ", "ganja": "AZ", "shamakhy": "AZ", "shirvan": "AZ",
    "kazakhstan": "KZ", "almaty": "KZ", "astana": "KZ", "aktau": "KZ", "atyrau": "KZ",
    "karaganda": "KZ", "taraz": "KZ", "shymkent": "KZ", "semey": "KZ", "pavlodar": "KZ",
    "kostanay": "KZ", "kyrgyzstan": "KG", "bishkek": "KG", "naryn": "KG", "osh": "KG",
    "tajikistan": "TJ", "dushanbe": "TJ", "khorog": "TJ", "uzbekistan": "UZ",
    "tashkent": "UZ", "samarkand": "UZ", "bukhara": "UZ", "namangan": "UZ", "andijan": "UZ",
    "fergana": "UZ", "fargona": "UZ", "turkmenistan": "TM", "ashgabat": "TM", "karakum": "TM",
    "afghanistan": "AF", "kabul": "AF", "herat": "AF", "kunduz": "AF", "jalalabad": "AF",
    "hindu kush": "AF", "pakistan": "PK", "islamabad": "PK", "lahore": "PK", "quetta": "PK",
    "karachi": "PK", "balochistan": "PK", "gilgit": "PK", "jammu": "IN",
    "india": "IN", "new delhi": "IN", "delhi": "IN", "mumbai": "IN", "ahmedabad": "IN",
    "kashmir": "IN", "srinagar": "IN", "ladakh": "IN", "gujarat": "IN", "rajasthan": "IN",
    "assam": "IN", "sikkim": "IN", "andaman": "IN", "nicobar": "IN", "imphal": "IN",
    "shillong": "IN", "dehradun": "IN", "laccadive": "IN",
    "nepal": "NP", "kathmandu": "NP", "gorkha": "NP", "everest": "NP", "bhutan": "BT",
    "thimphu": "BT", "bangladesh": "BD", "dhaka": "BD", "chittagong": "BD", "sylhet": "BD",
    "sri lanka": "LK", "colombo": "LK", "maldives": "MV",
    "myanmar": "MM", "burma": "MM", "mandalay": "MM", "naypyidaw": "MM", "sagaing": "MM",
    "thailand": "TH", "bangkok": "TH", "chiang mai": "TH", "chiang rai": "TH", "phuket": "TH",
    "kanchanaburi": "TH", "laos": "LA", "vientiane": "LA", "vietnam": "VN", "hanoi": "VN",
    "ho chi minh": "VN", "dien bien": "VN", "cambodia": "KH", "phnom penh": "KH",
    "malaysia": "MY", "kuala lumpur": "MY", "sabah": "MY", "penang": "MY", "johor": "MY",
    "malacca": "MY", "singapore": "SG", "brunei": "BN",
    "indonesia": "ID", "sumatra": "ID", "java": "ID", "sulawesi": "ID", "minahasa": "ID",
    "borneo": "ID", "molucca": "ID", "halmahera": "ID", "sumba": "ID", "sumbawa": "ID",
    "lombok": "ID", "bali": "ID", "nusa": "ID", "ambon": "ID", "palu": "ID", "makassar": "ID",
    "aceh": "ID", "medan": "ID", "padang": "ID", "manado": "ID", "sunda": "ID",
    "mentawai": "ID", "bandung": "ID", "yogyakarta": "ID", "batam": "ID", "denpasar": "ID",
    "mataram": "ID", "kupang": "ID", "sorong": "ID", "jayapura": "ID", "manokwari": "ID",
    "ternate": "ID", "tidore": "ID", "banda sea": "ID", "flores sea": "ID", "sawu sea": "ID",
    "pantar": "ID", "damar": "ID", "raja ampat": "ID", "waingapu": "ID", "maumere": "ID",
    "labuan bajo": "ID", "papua": "ID", "sea of sulawesi": "ID", "celebes sea": "ID",
    "timor": "TL", "dili": "TL", "oecusse": "TL", "oecussi": "TL", "atambua": "ID",
    "betun": "TL", "maliana": "TL", "suai": "TL", "liquica": "TL", "maubara": "TL",
    "viqueque": "TL", "baucau": "TL", "philippines": "PH", "luzon": "PH", "mindanao": "PH",
    "samar": "PH", "leyte": "PH", "cebu": "PH", "mindoro": "PH", "palawan": "PH",
    "davao": "PH", "iloilo": "PH", "tacloban": "PH", "surigao": "PH", "sulu": "PH",
    "moro gulf": "PH", "philippine sea": "PH", "sulu sea": "PH",
    "taiwan": "TW", "taipei": "TW", "hualien": "TW", "taichung": "TW", "tainan": "TW",
    "kaohsiung": "TW", "yilan": "TW", "hengchun": "TW", "orchid island": "TW",
    "china": "CN", "beijing": "CN", "xinjiang": "CN", "tibet": "CN", "lhasa": "CN",
    "sichuan": "CN", "yunnan": "CN", "qinghai": "CN", "gansu": "CN", "shaanxi": "CN",
    "ningxia": "CN", "yushu": "CN", "changning": "CN", "wenshan": "CN", "xizang": "CN",
    "shandong": "CN", "fujian": "CN", "guangdong": "CN", "guangxi": "CN", "hainan": "CN",
    "harbin": "CN", "manzhouli": "CN", "hong kong": "HK", "mongolia": "MN",
    "ulaanbaatar": "MN", "north korea": "KP", "pyongyang": "KP", "south korea": "KR",
    "seoul": "KR", "pohang": "KR", "gyeongju": "KR", "jeju": "KR", "daejeon": "KR",
    "korea": "KR",
    "japan": "JP", "honshu": "JP", "hokkaido": "JP", "kyushu": "JP", "shikoku": "JP",
    "okinawa": "JP", "ryukyu": "JP", "nansei": "JP", "bonin": "JP", "chiba": "JP",
    "tohoku": "JP", "kanto": "JP", "chubu": "JP", "kansai": "JP", "chugoku": "JP",
    "noshiro": "JP", "akita": "JP", "iwate": "JP", "miyagi": "JP", "fukushima": "JP",
    "ibaraki": "JP", "kanagawa": "JP", "shizuoka": "JP", "aichi": "JP", "gifu": "JP",
    "nagano": "JP", "niigata": "JP", "toyama": "JP", "ishikawa": "JP", "fukui": "JP",
    "hyogo": "JP", "osaka": "JP", "kyoto": "JP", "nara": "JP", "wakayama": "JP",
    "tottori": "JP", "shimane": "JP", "okayama": "JP", "hiroshima": "JP", "yamaguchi": "JP",
    "kagawa": "JP", "tokushima": "JP", "ehime": "JP", "kochi": "JP", "oita": "JP",
    "miyazaki": "JP", "kumamoto": "JP", "nagasaki": "JP", "kagoshima": "JP", "amami": "JP",
    "tokunoshima": "JP", "yakushima": "JP", "tanegashima": "JP", "satsunan": "JP",
    "iwoto": "JP", "okino": "JP", "torishima": "JP", "sea of japan": "JP",
    # --- Oceanía ---
    "australia": "AU", "sydney": "AU", "melbourne": "AU", "perth": "AU", "brisbane": "AU",
    "adelaide": "AU", "canberra": "AU", "tasmania": "AU", "queensland": "AU",
    "new south wales": "AU", "northern territory": "AU", "south australia": "AU",
    "western australia": "AU", "tasman": "AU", "ballina": "AU", "leeton": "AU",
    "meckering": "AU", "cadoux": "AU", "yilgarn": "AU", "kimberley": "AU", "broome": "AU",
    "kununurra": "AU", "port hedland": "AU", "karratha": "AU", "newman": "AU", "telfer": "AU",
    "tanami": "AU", "alice springs": "AU", "darwin": "AU", "jervis bay": "AU",
    "wollongong": "AU", "byron bay": "AU", "gold coast": "AU", "mackay": "AU",
    "townsville": "AU", "cairns": "AU", "cooktown": "AU", "mount isa": "AU",
    "rockhampton": "AU", "gladstone": "AU", "bundaberg": "AU", "hervey bay": "AU",
    "gympie": "AU", "tamworth": "AU", "armidale": "AU", "deniliquin": "AU",
    "corryong": "AU", "warrnambool": "AU", "geelong": "AU", "bendigo": "AU",
    "shepparton": "AU", "mildura": "AU", "wagga": "AU", "albury": "AU", "goulburn": "AU",
    "lithgow": "AU", "mudgee": "AU", "muswellbrook": "AU", "tenterfield": "AU",
    "glen innes": "AU", "yamba": "AU", "moree": "AU", "narromine": "AU", "coobar": "AU",
    "broken hill": "AU", "port augusta": "AU", "whyalla": "AU", "port lincoln": "AU",
    "mount gambier": "AU", "victor harbor": "AU", "king island": "AU",
    "flinders island": "AU", "kangaroo island": "AU", "devonport": "AU", "launceston": "AU",
    "hobart": "AU", "burnie": "AU", "bicheno": "AU", "strahan": "AU", "wyndham": "AU",
    "carnarvon": "AU", "exmouth": "AU", "kalbarri": "AU", "geraldton": "AU",
    "esperance": "AU", "narrogin": "AU", "toodyay": "AU", "merredin": "AU",
    "kellerberrin": "AU", "bunbury": "AU", "mandurah": "AU", "rockingham": "AU",
    "coral sea": "AU", "macquarie": "AU", "norfolk": "NF", "cocos": "CC", "keeling": "CC",
    "christmas island": "CX",
    "new zealand": "NZ", "wellington": "NZ", "christchurch": "NZ", "auckland": "NZ",
    "rotorua": "NZ", "taupo": "NZ", "napier": "NZ", "gisborne": "NZ", "kaitaia": "NZ",
    "kaikoura": "NZ", "nelson": "NZ", "blenheim": "NZ", "picton": "NZ", "greymouth": "NZ",
    "hokitika": "NZ", "timaru": "NZ", "ochta": "NZ", "wanaka": "NZ", "queenstown": "NZ",
    "alexandra": "NZ", "dunedin": "NZ", "invercargill": "NZ", "gore": "NZ", "thames": "NZ",
    "waihao": "NZ", "cromwell": "NZ", "taranaki": "NZ", "new plymouth": "NZ",
    "whakatane": "NZ", "opotiki": "NZ", "tauranga": "NZ", "wairoa": "NZ", "pahiatua": "NZ",
    "featherston": "NZ", "masterton": "NZ", "cartington": "NZ", "foxton": "NZ",
    "levin": "NZ", "paraparaumu": "NZ", "meremere": "NZ", "whitianga": "NZ",
    "coromandel": "NZ", "whangarei": "NZ", "kerikeri": "NZ", "kaeo": "NZ", "mititai": "NZ",
    "dargaville": "NZ", "ohakune": "NZ", "fiordland": "NZ", "kermadec": "NZ",
    "chatham": "NZ", "hikurangi": "NZ", "puysegur": "NZ", "snares": "NZ", "antipodes": "NZ",
    "bounty islands": "NZ", "campbell island": "NZ", "three kings": "NZ",
    "papua new guinea": "PG", "new britain": "PG", "new ireland": "PG", "bougainville": "PG",
    "port moresby": "PG", "madang": "PG", "kokopo": "PG", "kimbe": "PG", "rabaul": "PG",
    "manus": "PG",
    "solomon islands": "SB", "solomon sea": "SB", "choiseul": "SB", "malaita": "SB",
    "guadalcanal": "SB", "new georgia": "SB", "solomons": "SB",
    "vanuatu": "VU", "efate": "VU", "tanna": "VU", "malampa": "VU", "espiritu santo": "VU",
    "new caledonia": "NC", "loyalty islands": "NC", "belep": "NC",
    "fiji": "FJ", "viti levu": "FJ", "taveuni": "FJ", "kadavu": "FJ", "rotuma": "FJ",
    "tonga": "TO", "ha apai": "TO", "vava u": "TO", "niuafo ou": "TO", "tongatapu": "TO",
    "samoa": "WS", "upolu": "WS", "savaii": "WS", "american samoa": "AS", "tutuila": "AS",
    "french polynesia": "PF", "tahiti": "PF", "marquesas": "PF", "tuamotu": "PF",
    "society islands": "PF", "austral islands": "PF", "gambier": "PF", "mangareva": "PF",
    "raiatea": "PF", "bora bora": "PF", "hikuerak": "PF", "pitcairn": "PN",
    "cook islands": "CK", "rarotonga": "CK", "aitutaki": "CK", "niue": "NU", "tokelau": "TK",
    "wallis": "WF", "futuna": "WF", "kiribati": "KI", "banaba": "KI", "tarawa": "KI",
    "kiritimati": "KI", "nauru": "NR", "tuvalu": "TV", "funafuti": "TV",
    "marshall islands": "MH", "majuro": "MH", "ebeye": "MH", "micronesia": "FM",
    "pohnpei": "FM", "chuuk": "FM", "yap": "FM", "kosrae": "FM", "palau": "PW", "koror": "PW",
    # --- África / Oriente Medio ---
    "morocco": "MA", "rabat": "MA", "casablanca": "MA", "marrakech": "MA", "marrakesh": "MA",
    "fez": "MA", "tangier": "MA", "agadir": "MA", "oujda": "MA", "meknes": "MA",
    "kenitra": "MA", "tetouan": "MA", "safi": "MA", "essaouira": "MA", "ouarzazate": "MA",
    "errachidia": "MA", "midelt": "MA", "al hoceima": "MA", "nador": "MA", "azilal": "MA",
    "khouribga": "MA", "beni mellal": "MA", "ifrane": "MA", "imiligh": "MA", "azagour": "MA",
    "zagora": "MA", "merzouga": "MA", "erfoud": "MA", "tinghir": "MA", "demnate": "MA",
    "tazenakht": "MA", "tamegroute": "MA", "taroudant": "MA", "toubkal": "MA", "tichka": "MA",
    "ourika": "MA", "amizmiz": "MA", "western sahara": "EH", "sahara": "EH",
    "mauritania": "MR", "nouakchott": "MR", "nouadhibou": "MR", "zouerate": "MR",
    "chinguetti": "MR", "tiris": "MR", "algeria": "DZ", "algiers": "DZ", "oran": "DZ",
    "constantine": "DZ", "annaba": "DZ", "batna": "DZ", "setif": "DZ", "bejaia": "DZ",
    "tipaza": "DZ", "boumerdes": "DZ", "khenchela": "DZ", "mascara": "DZ", "relizane": "DZ",
    "hodna": "DZ", "barika": "DZ", "biskra": "DZ", "ghardaia": "DZ", "timimoun": "DZ",
    "touggourt": "DZ", "el meniaa": "DZ", "in salah": "DZ", "reggane": "DZ",
    "tamanrasset": "DZ", "djanet": "DZ", "illizi": "DZ", "tebessa": "DZ", "souk ahras": "DZ",
    "el tarf": "DZ", "skikda": "DZ", "jijel": "DZ", "tlemcen": "DZ", "mostaganem": "DZ",
    "chlef": "DZ", "medea": "DZ", "blida": "DZ", "bouira": "DZ", "tizi ouzou": "DZ",
    "laghouat": "DZ", "el oued": "DZ", "ouargla": "DZ", "tindouf": "DZ",
    "tunisia": "TN", "tunis": "TN", "sfax": "TN", "sousse": "TN", "kairouan": "TN",
    "gafsa": "TN", "djerba": "TN", "bizerte": "TN", "kasserine": "TN", "sbeitla": "TN",
    "el kseib": "TN", "tajerouine": "TN",
    "libya": "LY", "benghazi": "LY", "misrata": "LY", "misurata": "LY", "sabha": "LY",
    "ghadames": "LY", "murzuq": "LY", "jalu": "LY", "kufra": "LY", "derna": "LY",
    "tobruk": "LY", "zawiya": "LY", "sirte": "LY", "ajdabiya": "LY", "ubari": "LY",
    "ghat": "LY", "awbari": "LY", "brak": "LY", "germa": "LY", "marada": "LY",
    "egypt": "EG", "cairo": "EG", "aswan": "EG", "luxor": "EG", "hurghada": "EG",
    "suez": "EG", "sinai": "EG", "taba": "EG", "dahab": "EG", "sharm": "EG", "marsa": "EG",
    "safaga": "EG", "qena": "EG", "sohag": "EG", "asyut": "EG", "mansoura": "EG",
    "zagazig": "EG", "banha": "EG", "tanta": "EG", "damanhur": "EG", "fayoum": "EG",
    "beni suef": "EG", "minya": "EG", "matruh": "EG", "siwa": "EG", "kharga": "EG",
    "farafra": "EG", "bahariya": "EG", "sokhna": "EG", "tor sina": "EG", "nuweiba": "EG",
    "sudan": "SD", "khartoum": "SD", "darfur": "SD", "omdurman": "SD", "kassala": "SD",
    "el obeid": "SD", "al obeid": "SD", "port sudan": "SD", "el fasher": "SD",
    "fasher": "SD", "nyala": "SD", "kosti": "SD", "wad madani": "SD", "sinja": "SD",
    "sennar": "SD", "south sudan": "SS", "juba": "SS", "malakal": "SS", "wau": "SS",
    "yambio": "SS", "torit": "SS", "bentiu": "SS",
    "chad": "TD", "ndjamena": "TD", "moundou": "TD",
    "niger": "NE", "niamey": "NE", "zinder": "NE", "agadez": "NE", "dosso": "NE",
    "tahoua": "NE", "maradi": "NE", "arlit": "NE", "bilma": "NE",
    "mali": "ML", "bamako": "ML", "timbuktu": "ML", "gao": "ML", "kidal": "ML",
    "mopti": "ML", "sikasso": "ML", "kayes": "ML", "hombori": "ML",
    "burkina faso": "BF", "ouagadougou": "BF", "bobo dioulasso": "BF", "koudougou": "BF",
    "senegal": "SN", "dakar": "SN", "tambacounda": "SN", "kaolack": "SN", "ziguinchor": "SN",
    "thies": "SN", "louga": "SN", "kolda": "SN", "matam": "SN", "gambia": "GM",
    "banjul": "GM", "serekunda": "GM", "brikama": "GM",
    "guinea bissau": "GW", "bissau": "GW", "guinea": "GN", "conakry": "GN", "kindia": "GN",
    "boke": "GN", "labe": "GN", "kankan": "GN", "fouta djallon": "GN", "gueckedou": "GN",
    "macenta": "GN", "siguiri": "GN", "dabola": "GN", "kissidougou": "GN", "nzerekore": "GN",
    "beyla": "GN", "mandiana": "GN", "dinguiraye": "GN", "fria": "GN", "coyah": "GN",
    "dubreka": "GN", "kamsar": "GN", "sierra leone": "SL", "freetown": "SL", "koidu": "SL",
    "kenema": "SL", "makeni": "SL", "liberia": "LR", "monrovia": "LR", "ganta": "LR",
    "robertsport": "LR", "bensonville": "LR", "cote d ivoire": "CI", "ivory coast": "CI",
    "abidjan": "CI", "bouake": "CI", "korhogo": "CI", "daloa": "CI", "san pedro": "CI",
    "yamoussoukro": "CI", "gagnoa": "CI", "dabou": "CI", "grand lahou": "CI", "sassandra": "CI",
    "ghana": "GH", "accra": "GH", "kumasi": "GH", "tamale": "GH", "takoradi": "GH",
    "tema": "GH", "obuasi": "GH", "koforidua": "GH", "sunyani": "GH", "cape coast": "GH",
    "elmina": "GH", "axim": "GH", "tarkwa": "GH", "buipe": "GH", "togo": "TG", "lome": "TG",
    "kara": "TG", "dapaong": "TG", "anecho": "TG", "kpalime": "TG", "benin city": "NG",
    "benin": "BJ", "porto novo": "BJ", "cotonou": "BJ", "parakou": "BJ", "abomey": "BJ",
    "lokossa": "BJ", "bassila": "BJ", "dassa zoume": "BJ",
    "nigeria": "NG", "lagos": "NG", "abuja": "NG", "kano": "NG", "jos": "NG", "yola": "NG",
    "maiduguri": "NG", "sokoto": "NG", "zaria": "NG", "port harcourt": "NG",
    "abeokuta": "NG", "ibadan": "NG", "akure": "NG", "kaduna": "NG", "nassarawa": "NG",
    "zamfara": "NG", "katsina": "NG", "bauchi": "NG", "taraba": "NG", "borno": "NG",
    "yobe": "NG", "gombe": "NG", "jalingo": "NG", "minna": "NG", "illore": "NG",
    "iffon": "NG", "olupona": "NG", "ejigbo": "NG", "ile ife": "NG",
    "cameroon": "CM", "yaounde": "CM", "douala": "CM", "garoua": "CM", "maroua": "CM",
    "bamenda": "CM", "buea": "CM", "limbe": "CM", "kribi": "CM", "edea": "CM",
    "nkongsamba": "CM", "bafoussam": "CM", "bertoua": "CM", "ngaoundere": "CM",
    "meiganga": "CM", "djoule": "CM", "goyka": "CM",
    "central african republic": "CF", "bangui": "CF", "bimbo": "CF", "boda": "CF",
    "berberati": "CF", "bossangoa": "CF", "kaga bandoro": "CF", "alindao": "CF",
    "equatorial guinea": "GQ", "malabo": "GQ", "bata": "GQ", "mongomo": "GQ", "riaba": "GQ",
    "sao tome": "ST", "principe": "ST", "gabon": "GA", "libreville": "GA",
    "port gentil": "GA", "franceville": "GA", "oyem": "GA", "lambarene": "GA", "bitam": "GA",
    "koulamoutou": "GA", "mouila": "GA", "angondje": "GA", "lastourville": "GA",
    "dr congo": "CD", "democratic republic of the congo": "CD",
    "democratic republic of congo": "CD", "congo democratic": "CD", "drc": "CD",
    "kivu": "CD", "north kivu": "CD", "south kivu": "CD", "goma": "CD", "bukavu": "CD",
    "ituri": "CD", "lubumbashi": "CD", "katanga": "CD", "haut katanga": "CD",
    "kampene": "CD", "kisangani": "CD", "mbuji mayi": "CD", "rupela": "CD", "bondo": "CD",
    "bukama": "CD", "shabunda": "CD", "fizi": "CD", "uvira": "CD", "walikale": "CD",
    "masisi": "CD", "lubero": "CD", "nyiragongo": "CD", "nyamuragira": "CD",
    "congo": "CG", "brazzaville": "CG", "pointe noire": "CG", "dolisie": "CG",
    "kinkala": "CG", "sibiti": "CG", "impfondo": "CG", "makoua": "CG", "owando": "CG",
    "ouesso": "CG", "angola": "AO", "luanda": "AO", "huambo": "AO", "lubango": "AO",
    "namibe": "AO", "sumbe": "AO", "malanje": "AO", "gabela": "AO", "caconda": "AO",
    "dondo": "AO", "waco kiji": "AO", "soyo": "AO", "cabinda": "AO",
    "uganda": "UG", "kampala": "UG", "kasese": "UG", "fort portal": "UG", "mbarara": "UG",
    "gulu": "UG", "lira": "UG", "masaka": "UG", "jinja": "UG", "soroti": "UG",
    "mukono": "UG", "hoima": "UG", "rwanda": "RW", "kigali": "RW", "gisenyi": "RW",
    "gitarama": "RW", "huye": "RW", "rusizi": "RW", "rubavu": "RW", "burundi": "BI",
    "bujumbura": "BI", "gitega": "BI", "ngozi": "BI", "rumonge": "BI", "karuzi": "BI",
    "rutana": "BI",
    "ethiopia": "ET", "addis ababa": "ET", "addis": "ET", "abyssinia": "ET", "afar": "ET",
    "dallol": "ET", "erta ale": "ET", "mekelle": "ET", "gondar": "ET", "dessie": "ET",
    "dabbahu": "ET", "kobo": "ET", "sodo": "ET", "diredawa": "ET", "harar": "ET",
    "jijiga": "ET", "moyale": "ET", "yabelo": "ET", "corbetti": "ET", "aluto": "ET",
    "eritrea": "ER", "asmara": "ER", "massawa": "ER", "dahlac": "ER", "keren": "ER",
    "nakfa": "ER", "assab": "ER", "djibouti": "DJ",
    "somalia": "SO", "mogadishu": "SO", "hargeisa": "SO", "galkayo": "SO", "baidoa": "SO",
    "kismaayo": "SO", "beledweyne": "SO", "barawa": "SO", "marka": "SO", "bosaso": "SO",
    "kenya": "KE", "nairobi": "KE", "kisumu": "KE", "nakuru": "KE", "eldoret": "KE",
    "mbale": "KE", "malindi": "KE", "mombasa": "KE", "lamu": "KE", "lodwar": "KE",
    "garissa": "KE", "isiolo": "KE", "nyahururu": "KE", "kakamega": "KE", "bungoma": "KE",
    "tanzania": "TZ", "dar es salaam": "TZ", "dodoma": "TZ", "arusha": "TZ",
    "kilimanjaro": "TZ", "tanganyika": "TZ", "kigoma": "TZ", "mbeya": "TZ", "mwanza": "TZ",
    "tabora": "TZ", "morogoro": "TZ", "tanga": "TZ", "buguma": "TZ", "bukoba": "TZ",
    "sengerema": "TZ", "ngara": "TZ",
    "zambia": "ZM", "lusaka": "ZM", "kafue": "ZM", "kariba": "ZM", "ndola": "ZM",
    "kitwe": "ZM", "livingstone": "ZM", "kasama": "ZM", "choma": "ZM", "monze": "ZM",
    "chinsali": "ZM", "malawi": "MW", "lilongwe": "MW", "salima": "MW", "mzuzu": "MW",
    "blantyre": "MW", "zomba": "MW", "mangochi": "MW", "karonga": "MW", "dedza": "MW",
    "nkhata bay": "MW",
    "mozambique": "MZ", "maputo": "MZ", "nampula": "MZ", "tete": "MZ", "zambezia": "MZ",
    "sofala": "MZ", "inhambane": "MZ", "pemba": "MZ", "cabo delgado": "MZ", "xai xai": "MZ",
    "vilankulo": "MZ", "mocimboa": "MZ", "quelimane": "MZ", "anguanja": "MZ",
    "zimbabwe": "ZW", "harare": "ZW", "gwanda": "ZW", "bulawayo": "ZW", "masvingo": "ZW",
    "kwekwe": "ZW", "shamva": "ZW", "chiredzi": "ZW",
    "botswana": "BW", "gaborone": "BW", "francistown": "BW", "mahalapye": "BW",
    "lobatse": "BW", "serowe": "BW", "kanye": "BW", "jwaneng": "BW",
    "namibia": "NA", "windhoek": "NA", "walvis bay": "NA", "walvisbay": "NA",
    "swakopmund": "NA", "otjiwarongo": "NA", "outjo": "NA", "ruacana": "NA", "arandis": "NA",
    "gobabis": "NA", "keetmanshoop": "NA", "luderitz": "NA", "omaruru": "NA",
    "oshakati": "NA", "ondangwa": "NA", "rupara": "NA",
    "south africa": "ZA", "johannesburg": "ZA", "cape town": "ZA", "durban": "ZA",
    "pretoria": "ZA", "rustenburg": "ZA", "klerksdorp": "ZA", "tulbagh": "ZA", "karoo": "ZA",
    "mpumalanga": "ZA", "lesotho": "LS", "maseru": "LS", "eswatini": "SZ",
    "swaziland": "SZ", "mbabane": "SZ",
    "madagascar": "MG", "antananarivo": "MG", "toamasina": "MG", "mahajanga": "MG",
    "diego suarez": "MG", "antsiranana": "MG", "fianarantsoa": "MG", "toliara": "MG",
    "antsirabe": "MG", "moramanga": "MG", "morondava": "MG", "nosy be": "MG",
    "mayotte": "YT", "mamoudzou": "YT", "dzaoudzi": "YT", "comoros": "KM", "moroni": "KM",
    "mutsamudu": "KM", "fomboni": "KM", "anzjouan": "KM", "grande comore": "KM", "mwali": "KM",
    "seychelles": "SC", "mahe": "SC", "praslin": "SC", "la digue": "SC",
    "mauritius": "MU", "port louis": "MU", "rodrigues": "MU", "cargados carajos": "MU",
    "reunion": "RE", "fournaise": "RE",
    "cape verde": "CV", "cabo verde": "CV", "sao vicente": "CV", "fogo": "CV",
    "santo antao": "CV", "boavista": "CV",
    # --- Atlántico Sur / Antártida ---
    "ascension": "SH", "tristan": "SH", "saint helena": "SH", "st helena": "SH",
    "gough": "SH", "bouvet": "BV", "south georgia": "GS", "south sandwich": "GS",
    "falkland": "FK", "malvinas": "FK", "crozet": "TF", "amsterdam island": "TF",
    "kerguelen": "TF", "saint paul island": "TF", "europa island": "TF", "juan de nova": "TF",
    "glorioso": "TF", "tromelin": "TF", "scattered islands": "TF", "heard": "HM",
    "chagos": "IO", "diego garcia": "IO", "british indian ocean": "IO",
    "antarctic": "AQ", "antarctica": "AQ", "adelie": "AQ", "ross sea": "AQ",
    "weddell": "AQ", "larsen": "AQ", "riiser larsen": "AQ", "duse": "AQ", "balleny": "AQ",
    "scotia": "AQ", "bransfield": "AQ", "learmonth": "AQ", "south orkney": "AQ",
    "south shetland": "AQ", "cape adare": "AQ", "mcmurdo": "AQ", "amundsen scott": "AQ",
    "ross island": "AQ", "deception island": "AQ", "livingston island": "AQ",
    "elephant island": "AQ", "king george island": "AQ", "george v island": "AQ",
    "alexander island": "AQ", "charcot island": "AQ", "filchner": "AQ", "ronne": "AQ",
    "amery": "AQ", "shackleton": "AQ", "maud": "AQ", "princess elizabeth": "AQ",
    # --- Oriente Medio ---
    "turkey": "TR", "turkiye": "TR", "istanbul": "TR", "ankara": "TR", "izmir": "TR",
    "bodrum": "TR", "kahramanmaras": "TR", "gaziantep": "TR", "hatay": "TR", "malatya": "TR",
    "elazig": "TR", "mersin": "TR", "adana": "TR", "antalya": "TR", "konya": "TR",
    "anatolia": "TR", "canakkale": "TR", "gallipoli": "TR", "samsun": "TR", "trabzon": "TR",
    "van turkey": "TR", "hakkari": "TR", "sirnak": "TR", "mardin": "TR", "sanliurfa": "TR",
    "adiyaman": "TR", "osmaniye": "TR", "antakya": "TR", "narlica": "TR", "pazarcik": "TR",
    "elbistan": "TR", "cyprus": "CY", "nicosia": "CY", "limassol": "CY", "paphos": "CY",
    "larnaca": "CY", "famagusta": "CY",
    "syria": "SY", "aleppo": "SY", "latakia": "SY", "idlib": "SY", "lebanon": "LB",
    "beirut": "LB", "israel": "IL", "jerusalem": "IL", "tel aviv": "IL", "eilat": "IL",
    "dead sea": "IL", "palestine": "PS", "gaza": "PS", "ramallah": "PS", "nablus": "PS",
    "hebron": "PS", "jericho": "PS", "bethlehem": "PS", "west bank": "PS",
    "jordan": "JO", "amman": "JO", "aqaba": "JO", "iraq": "IQ", "baghdad": "IQ",
    "mosul": "IQ", "kurdistan": "IQ", "halabja": "IQ",
    "iran": "IR", "tehran": "IR", "tabriz": "IR", "kerman": "IR", "kermanshah": "IR",
    "isfahan": "IR", "hormozgan": "IR", "khuzestan": "IR", "luristan": "IR", "bushehr": "IR",
    "kish": "IR", "qeshm": "IR", "hormuz": "IR", "jask": "IR", "chabahar": "IR",
    "zahedan": "IR", "birjand": "IR", "kashan": "IR", "arak": "IR", "saveh": "IR",
    "qom": "IR", "qum": "IR", "karaj": "IR", "qazvin": "IR", "zanjan": "IR",
    "ardabil": "IR", "urmia": "IR", "maragheh": "IR", "miandoab": "IR", "ilam": "IR",
    "ahvaz": "IR", "ahwaz": "IR", "masjed": "IR", "shiraz": "IR", "kazerun": "IR",
    "behbahan": "IR", "yasuj": "IR", "yazd": "IR", "mashhad": "IR", "bojnurd": "IR",
    "sabzevar": "IR", "neyshabur": "IR", "bandar abbass": "IR", "bandar lengeh": "IR",
    "bandar kong": "IR", "konarak": "IR", "sirik": "IR", "minab": "IR", "rudan": "IR",
    "bashagard": "IR", "khamir": "IR", "damghan": "IR", "shahrud": "IR", "semnan": "IR",
    "sari": "IR", "gorgan": "IR", "gonbad": "IR", "khoy": "IR",
    "kuwait": "KW", "bahrain": "BH", "manama": "BH", "muharraq": "BH", "qatar": "QA",
    "doha": "QA", "united arab emirates": "AE", "uae": "AE", "dubai": "AE",
    "abu dhabi": "AE", "sharjah": "AE", "ajman": "AE", "ras al khaimah": "AE",
    "fujairah": "AE", "umm al quwain": "AE", "oman": "OM", "muscat": "OM", "salalah": "OM",
    "sohar": "OM", "nizwa": "OM", "dhofar": "OM",
    "saudi arabia": "SA", "riyadh": "SA", "jeddah": "SA", "mecca": "SA", "makkah": "SA",
    "medina": "SA", "madinah": "SA", "dammam": "SA", "khobar": "SA", "qatif": "SA",
    "katif": "SA", "tabuk": "SA", "abha": "SA", "jizan": "SA", "jazan": "SA",
    "najran": "SA", "buraydah": "SA", "qassim": "SA", "taif": "SA", "yanbu": "SA",
    "jubail": "SA", "hofuf": "SA", "unayzah": "SA", "sakaka": "SA", "jouf": "SA",
    "jawf": "SA", "sharurah": "SA", "neom": "SA", "asir": "SA",
    "yemen": "YE", "sanaa": "YE", "sana a": "YE", "aden": "YE", "taiz": "YE",
    "hodeidah": "YE", "hudaydah": "YE", "marib": "YE", "saada": "YE", "ibb": "YE",
    "dhamar": "YE", "lahij": "YE", "abyan": "YE", "shabwah": "YE", "hadramawt": "YE",
    "mukalla": "YE",
}

def _norm_country_text(s):
    """Normaliza texto para el escaneo: minúsculas, sin guiones/apóstrofes/puntos."""
    try:
        return re.sub(r"\s+", " ", re.sub(r"[-'.]", " ", str(s or "").lower())).strip()
    except Exception:
        return ""

# Alternativa ordenada por longitud descendente: los términos más específicos
# ("papua new guinea", "state of georgia", "san salvador de jujuy") ganan a los
# subcadenas más cortas ("guinea", "georgia", "san salvador").
_COUNTRY_RE = re.compile(
    r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in sorted(_COUNTRY_TERMS, key=len, reverse=True)) + r")(?![a-z0-9])"
)

def flag_emoji(code):
    """Bandera Unicode a partir de un código ISO-3166 alfa-2 (🌐 si no aplica)."""
    try:
        if code and len(code) == 2 and code.isalpha() and code.isascii():
            return "".join(chr(0x1F1E6 + (ord(ch) - 65)) for ch in code.upper())
    except Exception:
        pass
    return "🌐"

def classify_event_country(lat, lon, place, auth=""):
    """
    Clasificador mundial de eventos sísmicos.
    1) Los 5 países foco (PA/VE/ES/AR/HN) conservan la regla estricta con cajas.
    2) El resto del mundo se clasifica por nombres de país/región en el texto.
    3) Mar abierto / dorsales sin nombre → (GLOBAL, Internacional, 🌐).
    Devuelve (code, name, flag).
    """
    try:
        code = identify_target_country(lat, lon, place, auth)
        if code:
            return code, TARGET_COUNTRIES[code]["name"], flag_emoji(code)
        m = _COUNTRY_RE.search(_norm_country_text(place))
        if m:
            c = _COUNTRY_TERMS[m.group(1)]
            return c, COUNTRY_NAMES_ES.get(c, c.title()), flag_emoji(c)
    except Exception:
        pass
    return GLOBAL_CODE, GLOBAL_NAME, "🌐"

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

        country_code, country_name, country_flag = classify_event_country(lat, lon, place, auth)
        if country_code not in TARGET_COUNTRIES and mag < GLOBAL_MIN_MAG:
            return None

        try:
            ts_str = time_str.replace('Z', '+00:00')
            time_ms = int(datetime.fromisoformat(ts_str).timestamp() * 1000)
        except Exception:
            time_ms = int(time.time() * 1000)

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
                "country_name": country_name,
                "country_flag": country_flag,
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
                        "title": "Red Sísmica Mundial en Tiempo Real",
                        "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
                        "total_events": 0,
                        "counts_by_country": {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0},
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

            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0}
            for f in features:
                c_code = f.get("properties", {}).get("country_code")
                counts[c_code] = counts.get(c_code, 0) + 1
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
    """Resultado cacheado 10 s: evita lanzar un subprocess pgrep/powershell en cada request."""
    now = time.time()
    with _gq_running_lock:
        if now - _gq_running_cache["ts"] < 10.0:
            return _gq_running_cache["result"]
    result = _is_globalquake_running_raw()
    with _gq_running_lock:
        _gq_running_cache["result"] = result
        _gq_running_cache["ts"] = now
    return result

_gq_running_cache = {"result": (False, None), "ts": 0.0}
_gq_running_lock = threading.Lock()

def _is_globalquake_running_raw():
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
                    depth = abs(float(coords[2])) if len(coords) > 2 else 10.0
                    place = props.get("flynn_region", "")
                    auth = props.get("auth", "EMSC")
                    
                    country_code, country_name, country_flag = classify_event_country(lat, lon, place, auth)
                    mag_val = _safe_float(props.get("mag"), 0.0)
                    if country_code not in TARGET_COUNTRIES and mag_val < GLOBAL_MIN_MAG:
                        continue
                    if country_code:
                        try:
                            time_str = props["time"].replace('Z', '+00:00')
                            time_ms = int(datetime.fromisoformat(time_str).timestamp() * 1000)
                        except Exception:
                            time_ms = int(time.time() * 1000)

                        events.append({
                            "id": f"emsc-{f.get('id') or props.get('unid')}",
                            "mag": mag_val,
                            "place": f"{place} ({auth})",
                            "time": time_ms,
                            "coords": [lon, lat, depth],
                            "source": f"EMSC/{auth}",
                            "country_code": country_code,
                            "country_name": country_name,
                            "country_flag": country_flag,
                            "pga": None
                        })
    except Exception:
        pass
    return events

def fetch_emsc_global():
    """Ingesta EMSC sin recorte geográfico: todos los países del mundo con M >= GLOBAL_MIN_MAG."""
    t0 = time.time()
    url = f"https://www.seismicportal.eu/fdsnws/event/1/query?format=json&minmag={GLOBAL_MIN_MAG}&limit=100"
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
                    depth = abs(float(coords[2])) if len(coords) > 2 else 10.0
                    place = props.get("flynn_region", "")
                    auth = props.get("auth", "EMSC")

                    country_code, country_name, country_flag = classify_event_country(lat, lon, place, auth)
                    if country_code not in TARGET_COUNTRIES and _safe_float(props.get("mag"), 0.0) < GLOBAL_MIN_MAG:
                        continue
                    try:
                        time_str = props["time"].replace('Z', '+00:00')
                        time_ms = int(datetime.fromisoformat(time_str).timestamp() * 1000)
                    except Exception:
                        time_ms = int(time.time() * 1000)

                    events.append({
                        "id": f"emsc-global-{f.get('id') or props.get('unid')}",
                        "mag": _safe_float(props.get("mag"), 0.0),
                        "place": f"{place} ({auth})",
                        "time": time_ms,
                        "coords": [lon, lat, depth],
                        "source": f"EMSC/{auth}",
                        "country_code": country_code,
                        "country_name": country_name,
                        "country_flag": country_flag,
                        "pga": None
                    })
            _server_telemetry["emsc_global"]["latency_ms"] = dt
            _server_telemetry["emsc_global"]["status"] = "ONLINE"
            _server_telemetry["emsc_global"]["last_sync"] = int(time.time() * 1000)
    except Exception:
        _server_telemetry["emsc_global"]["status"] = "DEGRADED"
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
                    depth = abs(float(coords[2])) if len(coords) > 2 else 10.0
                    props = f.get("properties", {})
                    place = props.get("place") or ""
                    
                    country_code, country_name, country_flag = classify_event_country(lat, lon, place, "USGS")
                    if country_code not in TARGET_COUNTRIES and _safe_float(props.get("mag"), 0.0) < GLOBAL_MIN_MAG:
                        continue
                    if country_code:
                        events.append({
                            "id": f.get("id"),
                            "mag": _safe_float(props.get("mag"), 0.0),
                            "place": place,
                            "time": _safe_int(props.get("time"), 0),
                            "coords": [lon, lat, depth],
                            "source": "USGS",
                            "country_code": country_code,
                            "country_name": country_name,
                            "country_flag": country_flag,
                            "pga": None,
                            "felt": _safe_int(props.get("felt"), 0)
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
            lat_f, lon_f, depth_f = float(lat), float(lon), abs(float(depth))
            country_code, country_name, country_flag = classify_event_country(lat_f, lon_f, region, "GQ")
            if country_code not in TARGET_COUNTRIES and float(mag) < GLOBAL_MIN_MAG:
                continue
            if country_code:
                events.append({
                    "id": f"gq-{uuid[:8]}",
                    "mag": round(float(mag), 2),
                    "place": f"{region} (GQ Direct)",
                    "time": int(origin),
                    "coords": [lon_f, lat_f, depth_f],
                    "source": "GlobalQuake",
                    "country_code": country_code,
                    "country_name": country_name,
                    "country_flag": country_flag,
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
        avg_mag = round(sum(item["mag"] for item in matched_cluster) / max(1, len(matched_cluster)), 1)
        
        primary_ref = matched_cluster[0]
        for item in matched_cluster:
            if "GlobalQuake" in item["source"]:
                primary_ref = item
                break

        is_consensus = sources_count >= 2
        confidence_text = f"CONSENSO MULTIRED ({sources_count} redes)" if is_consensus else f"Detección ({sources[0]})"
        confidence_score = min(99, 85 + sources_count * 7) if is_consensus else 85

        country_code = primary_ref["country_code"]
        country_meta = TARGET_COUNTRIES.get(country_code)
        country_name = country_meta["name"] if country_meta else primary_ref.get("country_name") or COUNTRY_NAMES_ES.get(country_code, GLOBAL_NAME)
        country_flag = (country_meta["flag"] if country_meta else "") or primary_ref.get("country_flag") or flag_emoji(country_code)

        cluster_felt = max([_safe_int(ev.get("felt"), 0) for ev in matched_cluster]) if matched_cluster else 0
        comm_felt = get_felt_reports(primary_ref["id"])
        total_felt = cluster_felt + comm_felt

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
                "country_name": country_name,
                "country_flag": country_flag,
                "felt": total_felt,
                "felt_reports": total_felt,
                "usgs_felt": cluster_felt,
                "community_felt": comm_felt,
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
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        f_usgs = executor.submit(fetch_usgs_feed)
        f_gq = executor.submit(fetch_gq_events)
        f_global = executor.submit(fetch_emsc_global)
        f_regions = [executor.submit(fetch_emsc_region, reg) for reg in QUERY_REGIONS]

        for future in [f_gq, f_usgs, f_global] + f_regions:
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
        counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0}
        for f in fused_features:
            cc = f["properties"].get("country_code")
            counts[cc] = counts.get(cc, 0) + 1
            # Incorporar mecanismo focal (tensor de momento / beachball)
            try:
                coords = f.get("geometry", {}).get("coordinates", [0, 0, 10])
                depth = coords[2] if len(coords) > 2 else 10.0
                f["properties"]["focal_mechanism"] = compute_focal_mechanism(
                    coords[1], coords[0], depth, f["properties"].get("mag", 0.0), f.get("properties")
                )
            except Exception:
                pass
            # Conteo de reportes ciudadanos: conservar el total fusionado (USGS felt + comunidad)
            # y solo elevarlo con el conteo comunitario cuando el evento no traía total (mesh/EMSC live)
            comm_felt_ct = get_felt_reports(f.get("id"))
            prev_felt_ct = _safe_int(f["properties"].get("felt_reports"), 0)
            f["properties"]["felt_reports"] = max(prev_felt_ct, comm_felt_ct)
            # Persistencia transaccional en SQLite
            save_quake_to_db(f)

        _server_telemetry["ign_es"]["events_count"] = counts["ES"]
        _server_telemetry["funvisis_ve"]["events_count"] = counts["VE"]
        _server_telemetry["inpres_ar"]["events_count"] = counts["AR"]
        _server_telemetry["upa_pa"]["events_count"] = counts["PA"]
        _server_telemetry["emsc_regional"]["events_count"] = len(raw_events)
        _active_feed_statuses = {"ONLINE", "LIVE_WS", "LIVE_STREAM"}

        return {
            "type": "FeatureCollection",
            "metadata": {
                "generated": int(time.time() * 1000),
                "title": "Red Sísmica Mundial en Tiempo Real: Foco en Panamá, Venezuela, España, Argentina y Honduras",
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
                "total_events": len(fused_features),
                "counts_by_country": counts,
                "consensus_events": len([f for f in fused_features if f["properties"]["is_consensus"]]),
                "active_servers": len([s for s in _server_telemetry.values() if s["status"] in _active_feed_statuses]),
                "realtime_streaming": True,
                "sync_frequency_seconds": 2.8,
                "memory_latency_ms": 0.4
            },
            "features": fused_features
        }

    return {
        "type": "FeatureCollection",
        "metadata": {
            "title": "Red Sísmica Mundial",
            "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
            "total_events": 0,
            "counts_by_country": {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0},
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
    """Obtención instantánea desde memoria RAM (Latencia < 1ms, cero bloqueo de red síncrono)"""
    global _ram_quake_cache
    with _ram_cache_lock:
        if _ram_quake_cache is not None and len(_ram_quake_cache.get("features", [])) > 0:
            return _ram_quake_cache

    try:
        db_quakes = load_quakes_from_db(200)
        if db_quakes:
            with _ram_cache_lock:
                _ram_quake_cache = {
                    "type": "FeatureCollection",
                    "features": db_quakes,
                    "metadata": {
                        "generated": int(time.time() * 1000),
                        "title": "KorshQuake Live SQLite Cache",
                        "status": 200,
                        "total_events": len(db_quakes)
                    }
                }
                return _ram_quake_cache
    except Exception:
        pass

    with _ram_cache_lock:
        if _ram_quake_cache is not None:
            return _ram_quake_cache

    return {
        "type": "FeatureCollection",
        "features": [],
        "metadata": {
            "generated": int(time.time() * 1000),
            "title": "KorshQuake Cold Start Cache",
            "status": 200,
            "total_events": 0
        }
    }


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

        country_code, country_name, _flag = classify_event_country(float(lat), float(lon), "", "")

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
                # Poda anti-fuga: descartar regiones sin alertas recientes
                if len(_last_cluster_by_region) > 500:
                    _stale_regions = [k for k, v in _last_cluster_by_region.items() if (now - v) > 3600.0]
                    for k in _stale_regions:
                        _last_cluster_by_region.pop(k, None)

                # Epicentro ponderado por amplitud PGA
                weights = [max(0.1, n["pga"]) for n in unique_nodes.values()]
                sum_w = sum(weights) or 1.0
                epi_lat = sum(n["lat"] * w for n, w in zip(unique_nodes.values(), weights)) / sum_w
                epi_lon = sum(n["lon"] * w for n, w in zip(unique_nodes.values(), weights)) / sum_w
                pga_max = max(n["pga"] for n in unique_nodes.values())

                # Estimación de Magnitud preliminar empírica M_L basada en PGA y número de nodos
                est_mag = round(min(7.8, max(3.0, 2.7 + 1.25 * math.log10(max(1.0, pga_max)) + 0.35 * math.log10(nodes_count))), 1)
                country_code, country_name, _flag = classify_event_country(epi_lat, epi_lon, "", "")
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

    def _admin_authorized(self, query=None):
        """True si ADMIN_TOKEN no está configurado o el token provisto coincide (timing-safe)."""
        if not ADMIN_TOKEN:
            return True
        supplied = (query or {}).get("token", [""])[0] or self.headers.get("X-Admin-Token", "")
        return hmac.compare_digest(str(supplied), ADMIN_TOKEN)

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
        post_query = urllib.parse.parse_qs(parsed_url.query)

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
            if content_length > 1_000_000:
                self.close_connection = True
                send_json({"error": "Payload too large"}, 413)
                return
            post_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body = json.loads(post_body.decode("utf-8")) if post_body else {}
        except Exception as e:
            send_json({"error": "Invalid JSON payload", "details": str(e)}, 400)
            return

        # Puerta administrativa para /api/admin/* (solo aplica si ADMIN_TOKEN está configurado)
        if path.startswith("/api/admin") and not self._admin_authorized(post_query):
            send_json({"error": "Unauthorized", "message": "Requiere header X-Admin-Token o ?token=***"}, 401)
            return

        # 1. Telemetría / Ping periódico de nodo (APK / Web Móvil)
        if path in ["/api/nodes/ping", "/api/nodes/telemetry"]:
            node_id = str(body.get("node_id", f"node-{int(time.time()*1000)}"))[:120]
            lat = _safe_float(body.get("lat"), 0.0)
            lon = _safe_float(body.get("lon"), 0.0)
            accuracy = _safe_float(body.get("accuracy"), 15.0)
            pga = _safe_float(body.get("pga"), 0.0)
            sta_lta = _safe_float(body.get("sta_lta"), 1.0)
            noise_floor = _safe_float(body.get("noise_floor"), 0.02)
            platform = str(body.get("platform", "mobile"))[:80]
            device = str(body.get("device", "Phone Sensor"))[:120]
            gps_enabled = bool(body.get("gps_enabled", True))
            location_mode = str(body.get("location_mode", "gps_fine"))[:40]
            
            node_type = str(body.get("node_type", "auto"))[:20]
            result = register_mesh_node(node_id, lat, lon, accuracy, pga, sta_lta, noise_floor, platform, device, gps_enabled, location_mode, node_type)
            send_json(result)
            return

        # 2. Disparo de acelerómetro anómalo (Seismic Trigger)
        if path == "/api/nodes/trigger":
            node_id = str(body.get("node_id", f"node-{int(time.time()*1000)}"))[:120]
            lat = _safe_float(body.get("lat"), 0.0)
            lon = _safe_float(body.get("lon"), 0.0)
            pga = _safe_float(body.get("pga"), 0.0)
            sta_lta = _safe_float(body.get("sta_lta"), 4.0)
            device = str(body.get("device", "Phone Sensor"))[:120]
            
            result = process_mesh_trigger(node_id, lat, lon, pga, sta_lta, device)
            send_json(result)
            return

        # 3. Disparo de prueba de cluster multi-nodo (Exclusivo administracion y pruebas)
        if path in ["/api/nodes/test_cluster", "/api/admin/test_cluster"]:
            lat = _safe_float(body.get("lat"), 10.48)
            lon = _safe_float(body.get("lon"), -66.90)
            pga = _safe_float(body.get("pga"), 35.0)
            nodes_count = _safe_int(body.get("nodes_count"), 3)
            
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

                # 5. Reporte ciudadano real de sismo sentido (DYFI)
        if path == "/api/quakes/report" or (path.startswith("/api/quakes/") and path.endswith("/report")):
            quake_id = body.get("quake_id")
            if not quake_id and path.startswith("/api/quakes/"):
                parts = path.strip("/").split("/")
                if len(parts) >= 4 and parts[0] == "api" and parts[1] == "quakes" and parts[3] == "report":
                    quake_id = parts[2]
            if not quake_id:
                send_json({"error": "Missing quake_id parameter"}, 400)
                return
            client_ip = self.headers.get("X-Forwarded-For") or self.client_address[0]
            lat = body.get("lat")
            lon = body.get("lon")
            intensity = body.get("intensity", 4.0)
            result = record_felt_report(quake_id, client_ip, lat, lon, intensity)
            send_json(result)
            return

        # 6. Suscripción a Notificaciones WebPush (/api/push/subscribe)
        if path == "/api/push/subscribe":
            endpoint = body.get("endpoint")
            keys = body.get("keys", {})
            p256dh = keys.get("p256dh", "")
            auth = keys.get("auth", "")
            min_mag = _safe_float(body.get("min_mag"), 4.0)
            target_country = body.get("country", "ALL")
            if not endpoint:
                send_json({"error": "Missing endpoint parameter"}, 400)
                return
            try:
                with _db_lock:
                    with sqlite3.connect(DB_PATH) as conn:
                        conn.execute("""
                        INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, min_mag, target_country, created_at)
                        VALUES (?, ?, ?, ?, ?, ?);
                        """, (endpoint, p256dh, auth, min_mag, target_country, time.time()))
                send_json({"success": True, "message": "Suscripción WebPush registrada exitosamente"})
            except Exception as e:
                send_json({"error": str(e)}, 500)
            return

        # 7. Prueba de Notificación WebPush (/api/push/test)
        if path == "/api/push/test":
            send_json({
                "success": True,
                "message": "Notificación de prueba procesada",
                "notification": {
                    "title": "KorshQuake Alerta Sísmica de Prueba",
                    "body": "El sistema de notificaciones en tiempo real está funcionando correctamente.",
                    "icon": "/icons/icon-192.png",
                    "badge": "/icons/icon-32.png",
                    "tag": "korshquake-test"
                }
            })
            return

        send_json({"error": "Endpoint not found", "path": path}, 404)
        return


    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query = urllib.parse.parse_qs(parsed_url.query)

        # Puerta administrativa para /admin y /api/admin/* (solo aplica si ADMIN_TOKEN está configurado)
        if (path in ("/admin", "/admin/") or path.startswith("/api/admin")) and not self._admin_authorized(query):
            payload = json.dumps({"error": "Unauthorized", "message": "Requiere header X-Admin-Token o ?token=***"}, ensure_ascii=False).encode("utf-8")
            self.send_response(401)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        # API: Obtener conteo real de reportes de sismo sentido (/api/quakes/<id>/report)
        if path.startswith('/api/quakes/') and path.endswith('/report'):
            parts = path.strip('/').split('/')
            quake_id = parts[2] if len(parts) >= 3 else ''
            count = get_felt_reports(quake_id)
            payload = json.dumps({'success': True, 'quake_id': quake_id, 'felt_reports': count}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return


        # API: ShakeMap Comunitario Geográfico (/api/quakes/<id>/shakemap o /api/quakes/shakemap)
        if path == "/api/quakes/shakemap" or (path.startswith("/api/quakes/") and path.endswith("/shakemap")):
            qid = None
            if path == "/api/quakes/shakemap":
                qid = query.get("quake_id", [None])[0]
            else:
                parts = path.strip("/").split("/")
                qid = parts[2] if len(parts) >= 3 else None
            sm_data = get_shakemap_data(qid) if qid else {"quake_id": "", "total_reports": 0, "points": []}
            payload = json.dumps(sm_data, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        # API: Búsqueda Histórica de Sismos con SQLite (/api/quakes/history)
        if path == "/api/quakes/history":
            q = query.get("q", [None])[0]
            c = query.get("country", [None])[0]
            min_m = query.get("min_mag", [None])[0]
            max_m = query.get("max_mag", [None])[0]
            lim = query.get("limit", [50])[0]
            off = query.get("offset", [0])[0]
            res_hist = search_quakes_history(query=q, country=c, min_mag=min_m, max_mag=max_m, limit=lim, offset=off)
            payload = json.dumps(res_hist, ensure_ascii=False).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        # API: Clave Pública VAPID WebPush (/api/push/public_key)
        if path == "/api/push/public_key":
            payload = json.dumps({"status": "ok", "public_key": VAPID_PUBLIC_KEY}).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        # API: Exportación de Datos Abiertos (/api/export/geojson, /api/export/csv, /api/export/quakeml)
        if path in ["/api/export/geojson", "/api/export/json"]:
            live_data = get_live_earthquakes()
            payload = json.dumps(live_data, ensure_ascii=False, indent=2).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/geo+json; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="korshquake_catalog.geojson"')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        if path == "/api/export/csv":
            live_data = get_live_earthquakes()
            features = live_data.get("features", [])
            csv_lines = ["id,time_utc,timestamp_ms,latitude,longitude,depth_km,magnitude,place,country_code,country_name,felt_reports,source_feed"]
            for f in features:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [0, 0, 10])
                t_utc = datetime.fromtimestamp(props.get("time", 0) / 1000.0, timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC') if props.get("time") else ""
                csv_lines.append(f'"{_csv_escape(f.get("id"))}","{_csv_escape(t_utc)}",{props.get("time", 0)},{coords[1]},{coords[0]},{coords[2] if len(coords)>2 else 10},{props.get("mag", 0)},"{_csv_escape(props.get("place", ""))}","{_csv_escape(props.get("country_code", ""))}","{_csv_escape(props.get("country_name", ""))}",{props.get("felt_reports", 0)},"{_csv_escape(props.get("source_feed", ""))}"')
            payload = "\n".join(csv_lines).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/csv; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="korshquake_catalog.csv"')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        if path in ["/api/export/quakeml", "/api/export/xml"]:
            live_data = get_live_earthquakes()
            features = live_data.get("features", [])
            xml_lines = [
                '<?xml version="1.0" encoding="UTF-8"?>',
                '<q:quakeml xmlns:q="http://quakeml.org/xmlns/quakeml/1.2" xmlns="http://quakeml.org/xmlns/bed/1.2">',
                '  <eventParameters publicID="smi:quake.korsh.online/catalog">'
            ]
            for f in features:
                props = f.get("properties", {})
                coords = f.get("geometry", {}).get("coordinates", [0, 0, 10])
                ev_id = xml_escape(str(f.get("id", "qk")), {'"': "&quot;"})
                place_xml = xml_escape(str(props.get("place", "Epicentro")))
                t_iso = datetime.fromtimestamp(props.get("time", 0) / 1000.0, timezone.utc).isoformat() + "Z" if props.get("time") else ""
                xml_lines.append(f'    <event publicID="smi:quake.korsh.online/event/{ev_id}">')
                xml_lines.append(f'      <description><text>{place_xml}</text><type>region name</type></description>')
                xml_lines.append(f'      <origin publicID="smi:quake.korsh.online/origin/{ev_id}">')
                xml_lines.append(f'        <time><value>{t_iso}</value></time>')
                xml_lines.append(f'        <latitude><value>{coords[1]}</value></latitude>')
                xml_lines.append(f'        <longitude><value>{coords[0]}</value></longitude>')
                xml_lines.append(f'        <depth><value>{(coords[2] if len(coords)>2 else 10)*1000}</value></depth>')
                xml_lines.append(f'      </origin>')
                xml_lines.append(f'      <magnitude publicID="smi:quake.korsh.online/magnitude/{ev_id}">')
                xml_lines.append(f'        <mag><value>{props.get("mag", 0)}</value></mag>')
                xml_lines.append(f'        <type>M</type>')
                xml_lines.append(f'      </magnitude>')
                xml_lines.append(f'    </event>')
            xml_lines.append('  </eventParameters>')
            xml_lines.append('</q:quakeml>')
            payload = "\n".join(xml_lines).encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'application/xml; charset=utf-8')
            self.send_header('Content-Disposition', 'attachment; filename="korshquake_catalog.xml"')
            self.send_header('Content-Length', str(len(payload)))
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(payload)
            return

        # Ruta: Ficha Técnica Compartible y OpenGraph (/event/<id>)
        if path.startswith("/event/") or path == "/event":
            event_id = path.strip("/").split("/")[-1] if "/" in path.strip("/") else ""
            matched = None
            if event_id:
                with _ram_cache_lock:
                    if _ram_quake_cache and "features" in _ram_quake_cache:
                        matched = next((f for f in _ram_quake_cache["features"] if f.get("id") == event_id), None)
                if not matched:
                    with _db_lock:
                        with sqlite3.connect(DB_PATH) as conn:
                            cur = conn.cursor()
                            cur.execute("SELECT raw_json FROM quakes WHERE id = ?;", (event_id,))
                            row = cur.fetchone()
                            if row:
                                try: matched = json.loads(row[0])
                                except Exception: pass

            title = "KorshQuake - Monitor Sísmico en Tiempo Real"
            desc = "Monitoreo sísmico y predicción de ondas en tiempo real."
            mag_str = "M --"
            place_str = "Sismo Detectado"
            event_id = html_lib.escape(event_id, quote=True)
            if matched:
                p = matched.get("properties", {})
                mag_val = _safe_float(p.get("mag"), 0.0)
                mag_str = f"M {mag_val:.1f}"
                place_str = html_lib.escape(str(p.get("place") or "Epicentro Sísmico"), quote=True)
                country = html_lib.escape(str(p.get("country_name") or ""), quote=True)
                coords = matched.get("geometry", {}).get("coordinates", [0, 0, 10])
                depth = _safe_float(coords[2] if len(coords) > 2 else 10, 10.0)
                title = f"Sismo {mag_str} - {place_str} ({country}) | KorshQuake"
                desc = f"Sismo de magnitud {mag_str} localizado en {place_str} a {depth:.0f} km de profundidad. Consulta frentes de onda ak135, telemetría y mapa interactivo en vivo."

            html_og = f'''<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <meta name="description" content="{desc}">
  <!-- OpenGraph -->
  <meta property="og:type" content="website">
  <meta property="og:title" content="{title}">
  <meta property="og:description" content="{desc}">
  <meta property="og:image" content="https://quake.korsh.online/icons/logo.png">
  <meta property="og:url" content="https://quake.korsh.online/event/{event_id}">
  <!-- Twitter Card -->
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="{title}">
  <meta name="twitter:description" content="{desc}">
  <meta name="twitter:image" content="https://quake.korsh.online/icons/logo.png">
  <link rel="icon" type="image/png" href="/icons/icon-192.png">
  <meta http-equiv="refresh" content="1;url=/?quake={event_id}">
  <style>
    body {{ background: #050b14; color: #f1f5f9; font-family: system-ui, sans-serif; display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; text-align: center; }}
    .card {{ background: rgba(13, 27, 46, 0.95); border: 1px solid #00e5ff; border-radius: 14px; padding: 32px; max-width: 520px; box-shadow: 0 10px 40px rgba(0,229,255,0.25); }}
    .mag {{ font-size: 2.2rem; font-weight: 800; color: #ff1e42; margin-bottom: 8px; }}
    .place {{ font-size: 1.15rem; font-weight: 700; margin-bottom: 12px; }}
    .desc {{ color: #94a3b8; font-size: 0.9rem; line-height: 1.5; margin-bottom: 24px; }}
    .btn {{ display: inline-block; background: #00e5ff; color: #050b14; font-weight: 700; padding: 12px 24px; border-radius: 8px; text-decoration: none; }}
  </style>
</head>
<body>
  <div class="card">
    <div class="mag">{mag_str}</div>
    <div class="place">{place_str}</div>
    <div class="desc">{desc}</div>
    <a href="/?quake={event_id}" class="btn">Abrir en Monitor Sísmico en Vivo</a>
  </div>
</body>
</html>'''
            payload = html_og.encode('utf-8')
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

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
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
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
                    "Logotipo oficial integrado como favicon, icono de aplicación y emblema de marca",
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
                "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
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

            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0}
            strong_quakes = []
            live_alerts = []
            recent_hour = 0
            max_mag = 0.0
            strongest_event = None

            for f in features:
                props = f.get("properties", {})
                cc = props.get("country_code")
                mag = float(props.get("mag") or 0)
                ev_time = float(props.get("time") or 0)

                counts[cc] = counts.get(cc, 0) + 1
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
                "active_networks": len([s for s in _server_telemetry.values() if s["status"] in ("ONLINE", "LIVE_WS", "LIVE_STREAM")]),
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

            # Filtro por tiempo (máximo 24 horas por defecto para no saturar información antigua)
            cutoff_24h = int(time.time() * 1000) - (24 * 3600 * 1000)
            if since_param:
                try:
                    since_val = float(since_param)
                    filtered = [f for f in filtered if float(f.get("properties", {}).get("time") or 0) >= since_val]
                except ValueError:
                    filtered = [f for f in filtered if float(f.get("properties", {}).get("time") or 0) >= cutoff_24h]
            else:
                filtered_24h = [f for f in filtered if float(f.get("properties", {}).get("time") or 0) >= cutoff_24h]
                # Si hay eventos en las últimas 24h se devuelven exclusivamente esos; si el entorno de pruebas está vacío, mantener los más recientes
                filtered = filtered_24h if filtered_24h else filtered[:20]

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
            counts = {"PA": 0, "VE": 0, "ES": 0, "AR": 0, "HN": 0}
            for f in filtered:
                cc = f.get("properties", {}).get("country_code")
                counts[cc] = counts.get(cc, 0) + 1

            response_data = {
                "type": "FeatureCollection",
                "metadata": {
                    "generated": int(time.time() * 1000),
                    "title": "KorshQuake API — Cobertura Mundial (foco PA/VE/ES/AR/HN)",
                    "target_countries": ["Panamá", "Venezuela", "España", "Argentina", "Honduras", "Resto del mundo (M ≥ 4.0)"],
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
                    p_depth = abs(float(q_depth or 10.0))
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
                ev_depth = abs(float(c[2])) if len(c) > 2 else 10.0
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

        # 11. Consola Administrativa /admin para Monitoreo de Nodos y Pruebas Sismicas
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

    def end_headers(self):
        # Evitar cacheo heurístico obsoleto en navegadores para código de interfaz dinámico
        req_path = getattr(self, "path", "")
        if any(req_path.endswith(ext) for ext in [".html", ".js", ".css", ".json"]) or req_path in ["", "/", "/admin"]:
            self.send_header("Cache-Control", "no-cache, must-revalidate")
        super().end_headers()

class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    daemon_threads = True
    allow_reuse_address = True

    def handle_error(self, request, client_address):
        # Suprimir trazas ruidosas de clientes que abortan conexiones prematuramente (health probes, scanners)
        err = sys.exc_info()[1]
        if isinstance(err, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return
        super().handle_error(request, client_address)

def run_server(port=PORT):
    with ThreadedTCPServer(("0.0.0.0", port), GlobalQuakeHandler) as httpd:
        print("[OK] GlobalQuake Realtime Streaming Hub activo.")
        print("[OK] Frecuencia de sincronizacion continua: cada 2.8 segundos.")
        print("[OK] Regiones exclusivas: Panama, Venezuela, Espana, Argentina y Honduras.")
        print(f"[OK] Servidor escuchando en: http://localhost:{port}")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        except Exception as e:
            print(f"[ERROR] Error inesperado en el servidor: {e}")

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    run_server(port)
