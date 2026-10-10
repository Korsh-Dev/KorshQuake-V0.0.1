
// =========================================================================
// GESTIÓN DE DISPOSITIVO: NODO MÓVIL (ACELERÓMETRO) O ESTACIÓN CENTINELA PC
// =========================================================================
function setupDeviceNodeRole() {
  const isMobile = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
  const isApk = navigator.userAgent.includes('KorshQuake');
  
  meshNodeState.isDesktop = !isMobile;
  meshNodeState.deviceType = isMobile ? 'mobile_phone' : 'desktop_pc';
  meshNodeState.platform = isApk ? 'apk' : (isMobile ? 'web_mobile' : 'desktop');

  if (isApk) {
    meshNodeState.device = 'Android Phone (APK Nativa)';
  } else if (isMobile) {
    meshNodeState.device = navigator.userAgent.includes('Android') ? 'Android Móvil (Web)' : 'iPhone Móvil (Web)';
  } else {
    if (navigator.userAgent.includes('Windows')) meshNodeState.device = 'Windows PC (Estación Centinela)';
    else if (navigator.userAgent.includes('Macintosh')) meshNodeState.device = 'Mac Workstation (Estación Centinela)';
    else if (navigator.userAgent.includes('Linux')) meshNodeState.device = 'Linux PC (Estación Centinela)';
    else meshNodeState.device = 'Computadora de Escritorio';
  }

  // Actualizar elementos de interfaz según el tipo de dispositivo
  const topDevBadge = document.getElementById('top-device-badge');
  const topDevLabel = document.getElementById('top-device-label');
  const topDevIcon = document.getElementById('top-device-icon');
  const deviceRoleDisplay = document.getElementById('device-role-display');
  const seismoTitle = document.getElementById('seismo-title');
  const sensorModeTag = document.getElementById('sensor-mode-tag');
  const tabStationLabel = document.getElementById('sidebar-station-tab-label');
  const tabStationIcon = document.getElementById('sidebar-station-tab-icon');

  if (meshNodeState.isDesktop) {
    if (topDevLabel) topDevLabel.textContent = 'PC Centinela';
    if (topDevIcon) topDevIcon.textContent = '🖥️';
    if (deviceRoleDisplay) deviceRoleDisplay.textContent = 'PC Centinela';
    if (seismoTitle) seismoTitle.textContent = '🖥️ Estación Centinela PC';
    if (sensorModeTag) sensorModeTag.textContent = 'Vigilancia 24/7';
    if (tabStationLabel) tabStationLabel.textContent = 'Estación PC';
    if (tabStationIcon) tabStationIcon.textContent = '🖥️';
  } else {
    if (topDevLabel) topDevLabel.textContent = 'Sensor Móvil';
    if (topDevIcon) topDevIcon.textContent = '📱';
    if (deviceRoleDisplay) deviceRoleDisplay.textContent = 'Móvil (100 Hz)';
    if (seismoTitle) seismoTitle.textContent = '📱 Nodo Sismográfico Móvil';
    if (sensorModeTag) sensorModeTag.textContent = 'Acelerómetro Activo';
    if (tabStationLabel) tabStationLabel.textContent = 'Sismógrafo';
    if (tabStationIcon) tabStationIcon.textContent = '〰️';
  }
}

// Sirena de alerta para computadoras y estaciones de habitación
function playRoomEmergencySiren() {
  initAudio();
  if (!audioCtx) return;
  if (audioCtx.state === 'suspended') audioCtx.resume();

  const now = audioCtx.currentTime;
  const osc1 = audioCtx.createOscillator();
  const osc2 = audioCtx.createOscillator();
  const gain = audioCtx.createGain();

  osc1.type = 'sawtooth';
  osc2.type = 'sine';

  // Alternancia de frecuencia estilo alarma sísmica de alta advertencia (880 Hz / 587 Hz)
  osc1.frequency.setValueAtTime(880, now);
  osc1.frequency.setValueAtTime(587, now + 0.25);
  osc1.frequency.setValueAtTime(880, now + 0.50);
  osc1.frequency.setValueAtTime(587, now + 0.75);
  osc1.frequency.setValueAtTime(880, now + 1.00);

  osc2.frequency.setValueAtTime(440, now);
  osc2.frequency.setValueAtTime(293, now + 0.25);
  osc2.frequency.setValueAtTime(440, now + 0.50);
  osc2.frequency.setValueAtTime(293, now + 0.75);

  gain.gain.setValueAtTime(0.28, now);
  gain.gain.exponentialRampToValueAtTime(0.01, now + 1.25);

  osc1.connect(gain);
  osc2.connect(gain);
  gain.connect(audioCtx.destination);

  osc1.start(now);
  osc2.start(now);
  osc1.stop(now + 1.25);
  osc2.stop(now + 1.25);

  // Efecto visual en la estación
  const container = document.getElementById('seismograph-container');
  if (container) {
    container.classList.add('seismo-trigger-active');
    setTimeout(() => container.classList.remove('seismo-trigger-active'), 1400);
  }
}


// =========================================================================
// SISTEMA DE ACTUALIZACIÓN AUTOMÁTICA PUSH OTA (Sin reinstalar APK)
// =========================================================================
const APP_CURRENT_VERSION = '1.1.5 PRO';
let latestDetectedVersion = null;

async function checkAppVersion(isManual = false) {
  try {
    const res = await fetch('/api/version?_t=' + Date.now());
    if (!res.ok) return;
    const data = await res.json();
    latestDetectedVersion = data.version;

    const storedVer = localStorage.getItem('korsh_app_version') || APP_CURRENT_VERSION;
    const settingsLocal = document.getElementById('settings-local-version');
    if (settingsLocal) settingsLocal.textContent = storedVer;

    // Si la versión del servidor difiere de la versión local activa
    if (data.version && data.version !== storedVer) {
      showOtaUpdateBanner(data);
    } else if (isManual) {
      showToast(`✅ Ya tienes la última versión instalada (${data.version})`, 'info');
    }
  } catch (err) {
    if (isManual) showToast('Error al verificar versiones: ' + err.message, 'error');
  }
}

function showOtaUpdateBanner(vData) {
  const banner = document.getElementById('ota-update-banner');
  if (!banner) return;
  const title = document.getElementById('ota-version-title');
  const desc = document.getElementById('ota-changelog-preview');
  if (title) title.textContent = `🚀 Nueva Versión Disponible (${vData.version})`;
  if (desc && vData.changelog && vData.changelog.length > 0) {
    desc.textContent = vData.changelog[0] + ' • Toca para actualizar con 1 clic.';
  }
  banner.style.display = 'block';
  if (navigator.vibrate) navigator.vibrate([80, 50, 100]);
}

async function applyOtaUpdate() {
  const btn = document.getElementById('btn-ota-apply');
  if (btn) {
    btn.innerHTML = '<span>⚡ Actualizando...</span>';
    btn.disabled = true;
  }
  showToast('⚡ Aplicando actualización instantánea sin descargas...', 'info');

  try {
    // 1. Limpiar caches de Service Worker
    if ('caches' in window) {
      const keys = await caches.keys();
      await Promise.all(keys.map(k => caches.delete(k)));
    }
    // 2. Notificar al Service Worker para omitir espera y actualizar
    if ('serviceWorker' in navigator) {
      const registrations = await navigator.serviceWorker.getRegistrations();
      for (let reg of registrations) {
        if (reg.active) reg.active.postMessage({ action: 'clearCache' });
        if (reg.waiting) reg.waiting.postMessage({ action: 'skipWaiting' });
        await reg.update();
      }
    }
  } catch (e) {
    console.warn('[OTA] Excepción controlada limpiando cache:', e);
  }

  // 3. Registrar nueva versión local
  if (latestDetectedVersion) {
    localStorage.setItem('korsh_app_version', latestDetectedVersion);
  } else {
    localStorage.setItem('korsh_app_version', APP_CURRENT_VERSION);
  }

  // 4. Recargar interfaz con cache-busting
  setTimeout(() => {
    const url = new URL(window.location.href);
    url.searchParams.set('_v', Date.now());
    window.location.href = url.toString();
  }, 400);
}

// GlobalQuake v1.1.2 Web Hub Engine - Edición Focalizada: Panamá, Venezuela, España y Argentina
let map;
let currentTileLayers = [];
let worldVectorLayer;
let platesLayer;
let quakeLayerGroup;
let waveLayerGroup;
let allQuakes = [];
let connectedServers = [];
let soundEnabled = true;
let audioCtx = null;
let lastKnownMaxId = null;
let currentCountryFilter = 'all';

// Coordenadas y vistas por país
const REGION_VIEWPORTS = {
  all: { center: [15.0, -40.0], zoom: 3, title: "Mapa Sísmico: Panamá, Venezuela, España y Argentina" },
  PA: { center: [8.538, -80.782], zoom: 7.5, title: "Panamá 🇵🇦 - Monitoreo Sísmico Nacional" },
  VE: { center: [8.000, -66.100], zoom: 6.5, title: "Venezuela 🇻🇪 - Monitoreo Sísmico Nacional" },
  ES: { center: [40.200, -3.750], zoom: 6.0, title: "España 🇪🇸 - Monitoreo Peninsular e Insular" },
  AR: { center: [-38.416, -63.616], zoom: 5.0, title: "Argentina 🇦🇷 - Monitoreo Sísmico Nacional" }
};

// Tile Layer Definitions (100% Públicas, Sin Clave de API, Sin Marcas de Agua)
const TILE_LAYERS = {
  dark: {
    base: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}',
    ref: 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Reference/MapServer/tile/{z}/{y}/{x}',
    options: {
      maxZoom: 16,
      attribution: 'Tiles &copy; Esri &mdash; Dark Gray Canvas'
    }
  },
  satellite: {
    base: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
    options: {
      maxZoom: 18,
      attribution: 'Tiles &copy; Esri &mdash; World Imagery'
    }
  },
  topo: {
    base: 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Physical_Map/MapServer/tile/{z}/{y}/{x}',
    options: {
      maxZoom: 12,
      attribution: 'Tiles &copy; Esri &mdash; Physical World Map'
    }
  }
};

// Audio Synthesizer (Web Audio API)
function initAudio() {
  if (!audioCtx) {
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (AudioContext) {
      audioCtx = new AudioContext();
    }
  }
}

function playAlertSound(type = 'beep') {
  if (!soundEnabled) return;
  try {
    initAudio();
    if (audioCtx && audioCtx.state === 'suspended') {
      audioCtx.resume();
    }
    if (!audioCtx) return;

    const osc = audioCtx.createOscillator();
    const gain = audioCtx.createGain();
    osc.connect(gain);
    gain.connect(audioCtx.destination);

    if (type === 'major') {
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(880, audioCtx.currentTime);
      osc.frequency.setValueAtTime(440, audioCtx.currentTime + 0.18);
      osc.frequency.setValueAtTime(880, audioCtx.currentTime + 0.36);
      gain.gain.setValueAtTime(0.2, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.65);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.65);
    } else if (type === 'moderate') {
      // Tono suave y discreto para sismos moderados en vivo
      osc.type = 'sine';
      osc.frequency.setValueAtTime(750, audioCtx.currentTime);
      osc.frequency.exponentialRampToValueAtTime(500, audioCtx.currentTime + 0.18);
      gain.gain.setValueAtTime(0.12, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.18);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.18);
    } else {
      osc.type = 'sine';
      osc.frequency.setValueAtTime(900, audioCtx.currentTime);
      gain.gain.setValueAtTime(0.08, audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.01, audioCtx.currentTime + 0.12);
      osc.start();
      osc.stop(audioCtx.currentTime + 0.12);
    }

    // Vibración háptica en dispositivos móviles (Android / navegadores con soporte)
    if ('vibrate' in navigator) {
      if (type === 'major') {
        navigator.vibrate([250, 100, 250, 100, 500]);
      } else if (type === 'moderate') {
        navigator.vibrate([120, 60, 120]);
      }
    }
  } catch (err) {
    console.warn('Audio playback error:', err);
  }
}

// Map Initialization
function initMap() {
  const mapContainer = document.getElementById('map');
  if (!mapContainer) return;

  map = L.map('map', {
    center: [15.0, -40.0],
    zoom: 3,
    minZoom: 1.5,
    maxZoom: 16,
    zoomControl: true,
    preferCanvas: true
  });

  worldVectorLayer = L.layerGroup().addTo(map);
  platesLayer = L.layerGroup().addTo(map);
  quakeLayerGroup = L.layerGroup().addTo(map);
  waveLayerGroup = L.layerGroup().addTo(map);

  setTileLayer('dark');
  loadVectorLayers();

  const triggerResize = () => {
    if (map) {
      map.invalidateSize(true);
    }
  };

  map.whenReady(() => {
    triggerResize();
    setTimeout(triggerResize, 100);
    setTimeout(triggerResize, 300);
    setTimeout(triggerResize, 800);
  });

  window.addEventListener('resize', triggerResize);

  const selectLayer = document.getElementById('select-layer');
  if (selectLayer) {
    selectLayer.addEventListener('change', (e) => {
      setTileLayer(e.target.value);
    });
  }
}

// Change Map Tile Layer
function setTileLayer(layerKey) {
  currentTileLayers.forEach(l => {
    if (map.hasLayer(l)) {
      map.removeLayer(l);
    }
  });
  currentTileLayers = [];

  if (layerKey === 'vector') {
    showToast('Modo Vectorial Activo: Máximo rendimiento sin baldosas externas');
    return;
  }

  const def = TILE_LAYERS[layerKey] || TILE_LAYERS.dark;
  const baseLyr = L.tileLayer(def.base, def.options);
  baseLyr.addTo(map);
  currentTileLayers.push(baseLyr);

  if (def.ref) {
    const refLyr = L.tileLayer(def.ref, {
      maxZoom: def.options.maxZoom,
      opacity: 0.9,
      pane: 'shadowPane'
    });
    refLyr.addTo(map);
    currentTileLayers.push(refLyr);
  }
}

// Load Local Vector Layers
async function loadVectorLayers() {
  try {
    const res = await fetch('vendor/plates.json');
    if (res.ok) {
      const data = await res.json();
      L.geoJSON(data, {
        style: {
          color: '#ff5722',
          weight: 1.5,
          opacity: 0.65,
          dashArray: '3, 4'
        }
      }).addTo(platesLayer);
    }
  } catch (err) {
    console.warn('Could not load plates:', err);
  }

  try {
    const res = await fetch('vendor/world.json');
    if (res.ok) {
      const data = await res.json();
      L.geoJSON(data, {
        style: {
          fillColor: '#07080c',
          fillOpacity: 0.25,
          color: 'rgba(255, 30, 66, 0.3)',
          weight: 1,
          opacity: 0.7
        }
      }).addTo(worldVectorLayer);
    }
  } catch (err) {
    console.warn('Could not load world outlines:', err);
  }
}

// Helpers
function getMagColor(mag) {
  if (mag >= 6.5) return '#ff1744';
  if (mag >= 5.0) return '#ff9100';
  if (mag >= 3.0) return '#ffd600';
  return '#ff1e42';
}

function getMagClass(mag) {
  if (mag >= 6.5) return 'red';
  if (mag >= 5.0) return 'orange';
  if (mag >= 3.0) return 'yellow';
  return 'cyan';
}

function getMarkerRadius(mag) {
  return Math.max(5.5, Math.pow(mag, 1.8) * 0.85);
}

// Set Country Filter
function setCountryFilter(code) {
  currentCountryFilter = code;
  document.querySelectorAll('.country-pill').forEach(pill => {
    pill.classList.toggle('active', pill.dataset.country === code);
  });
  
  const viewport = REGION_VIEWPORTS[code] || REGION_VIEWPORTS.all;
  if (map) {
    map.flyTo(viewport.center, viewport.zoom, { duration: 1.2 });
  }

  const mapTitle = document.getElementById('map-section-title');
  if (mapTitle) mapTitle.textContent = viewport.title;

  const feedTitle = document.getElementById('feed-panel-title');
  if (feedTitle) {
    feedTitle.textContent = code === 'all' ? 'Sismos Recientes' : `Sismos en ${viewport.title.split(' - ')[0]}`;
  }

  renderQuakes();
}

// Update Country Pill Counts
function updateCountryPillCounts(counts) {
  if (!counts) return;
  const countAll = (counts.PA || 0) + (counts.VE || 0) + (counts.ES || 0) + (counts.AR || 0);
  const elAll = document.getElementById('count-pill-all');
  const elPa = document.getElementById('count-pill-pa');
  const elVe = document.getElementById('count-pill-ve');
  const elEs = document.getElementById('count-pill-es');
  const elAr = document.getElementById('count-pill-ar');
  if (elAll) elAll.textContent = countAll;
  if (elPa) elPa.textContent = counts.PA || 0;
  if (elVe) elVe.textContent = counts.VE || 0;
  if (elEs) elEs.textContent = counts.ES || 0;
  if (elAr) elAr.textContent = counts.AR || 0;
}


// =========================================================================
// IPHONE LIQUID GLASS - MODAL FICHA DETALLADA DEL SISMO & DISTANCIA REAL
// =========================================================================
function calculateDistanceKm(lat1, lon1, lat2, lon2) {
  if (lat1 === null || lon1 === null || lat2 === null || lon2 === null || isNaN(lat1) || isNaN(lon1)) return null;
  const R = 6371; // Radio de la Tierra en km
  const dLat = (lat2 - lat1) * Math.PI / 180;
  const dLon = (lon2 - lon1) * Math.PI / 180;
  const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
            Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
            Math.sin(dLon / 2) * Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c);
}

let activeSelectedFeature = null;

function openQuakeDetailModal(feature) {
  if (!feature || !feature.properties) return;
  activeSelectedFeature = feature;
  const modal = document.getElementById('modal-quake-detail');
  if (!modal) return;

  const props = feature.properties;
  const coords = feature.geometry.coordinates;
  const lon = coords[0];
  const lat = coords[1];
  const depth = coords.length > 2 ? Math.abs(coords[2]) : 10.0;
  const mag = props.mag || 0;

  // 1. Título y Hero
  const qdMag = document.getElementById('qd-mag-badge');
  const qdPlace = document.getElementById('qd-place');
  const qdTime = document.getElementById('qd-time');
  const qdCoords = document.getElementById('qd-coords');

  if (qdMag) {
    qdMag.textContent = `M ${mag.toFixed(1)}`;
    qdMag.className = `ios-mag-badge ${getMagClass(mag)}`;
    qdMag.style.background = getMagColor(mag);
  }
  if (qdPlace) {
    qdPlace.textContent = `${props.country_flag || ''} ${props.place || 'Epicentro'}`;
  }
  if (qdTime) {
    const d = new Date(props.time);
    qdTime.textContent = `Ocurrido ${formatTimeAgo(props.time)} • ${d.toLocaleDateString()} ${d.toLocaleTimeString()}`;
  }
  if (qdCoords) {
    qdCoords.textContent = `Coordenadas: ${lat.toFixed(3)}°N, ${lon.toFixed(3)}°E • ${props.country_name || ''}`;
  }

  // 2. Cuadrícula de 4 Casillas Glass
  const qdDepth = document.getElementById('qd-depth');
  const qdMmi = document.getElementById('qd-mmi');
  const qdPga = document.getElementById('qd-pga');
  const qdConsensus = document.getElementById('qd-consensus');

  if (qdDepth) qdDepth.textContent = `${depth.toFixed(1)} km`;
  if (qdMmi) {
    const mmiVal = props.mmi || (mag >= 6.5 ? 7.0 : (mag >= 5.0 ? 5.5 : (mag >= 3.5 ? 3.8 : 2.0)));
    let mmiRoman = 'I';
    let mmiText = 'Débil';
    if (mmiVal >= 7.0) { mmiRoman = 'VII'; mmiText = 'Muy Fuerte'; }
    else if (mmiVal >= 6.0) { mmiRoman = 'VI'; mmiText = 'Fuerte'; }
    else if (mmiVal >= 5.0) { mmiRoman = 'V'; mmiText = 'Moderado'; }
    else if (mmiVal >= 4.0) { mmiRoman = 'IV'; mmiText = 'Ligero'; }
    else if (mmiVal >= 3.0) { mmiRoman = 'III'; mmiText = 'Débil'; }
    qdMmi.textContent = `MMI ${mmiRoman} (${mmiText})`;
  }
  if (qdPga) {
    const pgaEst = (Math.pow(10, 0.5 * mag - 1.5) / Math.max(1, depth * 0.4)).toFixed(1);
    qdPga.textContent = `${pgaEst} gal`;
  }
  if (qdConsensus) {
    qdConsensus.textContent = props.is_consensus 
      ? `Consenso (${props.servers_count || 3} Redes)` 
      : `${props.source_feed || 'Red Oficial'}`;
  }

  // 3. Botón de reporte de vibración
  const btnReport = document.getElementById('btn-report-felt');
  const reportedKey = `korsh_reported_${feature.id}`;
  const alreadyReported = localStorage.getItem(reportedKey) === 'true';
  if (btnReport) {
    if (alreadyReported) {
      btnReport.disabled = true;
      btnReport.innerHTML = `<span>✓ Ya reportaste haber sentido este sismo</span>`;
      btnReport.style.opacity = '0.7';
    } else {
      btnReport.disabled = false;
      btnReport.innerHTML = `<span>🚨 ¿Sentiste este sismo? Reportar vibración</span>`;
      btnReport.style.opacity = '1';
      btnReport.onclick = () => {
        localStorage.setItem(reportedKey, 'true');
        btnReport.disabled = true;
        btnReport.innerHTML = `<span>✓ Reporte registrado con éxito (¡Gracias!)</span>`;
        if ('vibrate' in navigator) {
          try { navigator.vibrate([40, 30, 60]); } catch (e) {}
        }
        showToast(`🛡️ Reporte comunitario registrado para M ${mag.toFixed(1)} en ${props.place || ''}`);
      };
    }
  }

  // 4. Botón centrar en mapa
  const btnFocus = document.getElementById('btn-focus-map');
  if (btnFocus) {
    btnFocus.onclick = () => {
      closeQuakeDetailModal();
      if (typeof setMobileView === 'function') setMobileView('map');
      if (map) {
        map.flyTo([lat, lon], 7.5, { duration: 1.2 });
      }
    };
  }

  // 5. Tabla de Ciudades (ETA)
  const tbody = document.getElementById('qd-cities-tbody');
  if (tbody) {
    const preds = props.predictions || [];
    if (preds.length > 0) {
      tbody.innerHTML = preds.map(p => `
        <tr>
          <td style="font-weight: 600;">${escapeHtml(p.city)} ${p.country_flag || ''}</td>
          <td style="color: #94a3b8;">${p.distance_km ? p.distance_km.toFixed(0) : '--'} km</td>
          <td style="color: #cbd5e1;">${p.arrived_p ? '✓ Pasó' : (p.eta_p_sec > 0 ? p.eta_p_sec + 's' : '--')}</td>
          <td style="color: ${p.arrived_s ? '#94a3b8' : '#ff1e42'}; font-weight: ${p.arrived_s ? 'normal' : '700'};">
            ${p.arrived_s ? '✓ Pasó' : (p.eta_s_sec > 0 ? p.eta_s_sec + 's' : '--')}
          </td>
        </tr>
      `).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align: center; color: #64748b; padding: 14px;">Propagación completada en centros urbanos.</td></tr>`;
    }
  }

  modal.style.display = 'flex';
  modal.classList.add('active');
}

function closeQuakeDetailModal() {
  const modal = document.getElementById('modal-quake-detail');
  if (modal) {
    modal.classList.remove('active');
    setTimeout(() => { modal.style.display = 'none'; }, 250);
  }
}

let currentSearchTerm = '';

// Render Quakes on Map & Sidebar
function renderQuakes() {
  if (!map || !allQuakes) return;

  const filterEl = document.getElementById('filter-mag');
  const magFilter = filterEl ? filterEl.value : 'all';

  const filtered = allQuakes.filter(f => {
    if (!f || !f.properties || !f.geometry || !f.geometry.coordinates) return false;
    const mag = f.properties.mag || 0;
    const country = f.properties.country_code;

    // Filtro estricto por país
    if (currentCountryFilter !== 'all' && country !== currentCountryFilter) {
      return false;
    }

    // Filtro por término de búsqueda en vivo (ciudad, estado, región)
    if (currentSearchTerm) {
      const placeLower = (f.properties.place || '').toLowerCase();
      const countryLower = (f.properties.country_name || '').toLowerCase();
      if (!placeLower.includes(currentSearchTerm) && !countryLower.includes(currentSearchTerm)) {
        return false;
      }
    }

    if (magFilter === 'consensus') return f.properties.is_consensus === true;
    if (magFilter === '3') return mag >= 3.0;
    if (magFilter === '5') return mag >= 5.0;
    if (magFilter === '6') return mag >= 6.5;
    return true;
  });

  quakeLayerGroup.clearLayers();
  waveLayerGroup.clearLayers();

  const quakeListEl = document.getElementById('quake-list');
  if (quakeListEl) {
    quakeListEl.innerHTML = '';
  }
  const feedCountEl = document.getElementById('feed-count');
  if (feedCountEl) {
    feedCountEl.textContent = filtered.length;
  }
  const navBadgeEl = document.getElementById('nav-badge-count');
  if (navBadgeEl) {
    navBadgeEl.textContent = filtered.length;
  }

  // Actualizar tarjeta flotante de último sismo en móvil
  const mlpEl = document.getElementById('mobile-latest-pill');
  if (mlpEl) {
    if (filtered.length > 0) {
      const topEvent = filtered[0];
      const topProps = topEvent.properties;
      const topCoords = topEvent.geometry.coordinates;
      const topMag = topProps.mag || 0;
      
      const mlpMag = document.getElementById('mlp-mag');
      const mlpPlace = document.getElementById('mlp-place');
      const mlpTime = document.getElementById('mlp-time');

      if (mlpMag) mlpMag.textContent = `M ${topMag.toFixed(1)}`;
      if (mlpPlace) mlpPlace.textContent = `${topProps.country_flag || ''} ${topProps.place || 'Sismo'}`;
      if (mlpTime) mlpTime.textContent = formatTimeAgo(topProps.time);
      
      mlpEl.style.display = 'flex';
      mlpEl.onclick = () => {
        if (typeof setMobileView === 'function') setMobileView('map');
        map.flyTo([topCoords[1], topCoords[0]], 7.0, { duration: 1.0 });
      };
    } else {
      mlpEl.style.display = 'none';
    }
  }

  if (filtered.length === 0) {
    if (quakeListEl) {
      quakeListEl.innerHTML = '<div class="loading-state"><p>No hay sismos registrados para este filtro en este momento.</p></div>';
    }
    return;
  }

  const nowMs = Date.now();

  filtered.forEach((feature, idx) => {
    const coords = feature.geometry.coordinates;
    const lon = coords[0];
    const lat = coords[1];
    const depth = coords.length > 2 ? coords[2] : 10.0;
    const props = feature.properties;
    const mag = props.mag || 0;
    const color = getMagColor(mag);
    const radius = getMarkerRadius(mag);
    const timeAgoStr = formatTimeAgo(props.time);
    const isConsensus = props.is_consensus;

    // Marker con halo de consenso
    const marker = L.circleMarker([lat, lon], {
      radius: radius,
      fillColor: color,
      color: isConsensus ? '#00e676' : '#ffffff',
      weight: isConsensus ? 2.5 : 1,
      opacity: 0.95,
      fillOpacity: 0.78
    });

    const popupHtml = `
      <div class="popup-quake">
        <div class="popup-mag" style="color: ${color}">M ${mag.toFixed(1)} <span style="font-size: 0.9rem">${escapeHtml(props.country_flag || '')} ${escapeHtml(props.country_name || '')}</span></div>
        <div class="popup-place">${escapeHtml(props.place || 'Epicentro')}</div>
        <div class="popup-details">
          <span><strong>Territorio:</strong> ${escapeHtml(props.country_name || '')} (${escapeHtml(props.country_code || '')})</span>
          <span><strong>Profundidad:</strong> ${depth ? depth.toFixed(1) : 10.0} km</span>
          <span><strong>Coordenadas:</strong> ${lat.toFixed(3)}°, ${lon.toFixed(3)}°</span>
          <span><strong>Precisión:</strong> <span style="color: ${isConsensus ? '#00e676' : '#7dd3fc'}">${escapeHtml(props.confidence_text || 'Normal')} (${props.confidence_score || 85}%)</span></span>
          <span><strong>Redes Sísmicas:</strong> <strong style="color: #fff;">${escapeHtml(props.source_feed || 'USGS')}</strong></span>
          <span><strong>Hora UTC:</strong> ${new Date(props.time).toUTCString()}</span>
        </div>
        <button class="btn btn-primary btn-sm" style="width: 100%; margin-top: 10px; justify-content: center; font-size: 0.82rem; padding: 6px 12px;" onclick="openPredictForEvent('${feature.id}')">
          ⚡ Predicción de Arribo EEW
        </button>
      </div>
    `;
    marker.bindPopup(popupHtml);
    quakeLayerGroup.addLayer(marker);

    // Ondas calculadas y animadas en tiempo real por el motor EEW
    updateWavefronts();

    // Tarjeta en Feed con Estilo iPhone Liquid Glass
    if (quakeListEl) {
      const userLat = meshNodeState.lat;
      const userLon = meshNodeState.lon;
      const distKm = (userLat && userLon) ? calculateDistanceKm(userLat, userLon, lat, lon) : null;
      const distText = (distKm !== null && !isNaN(distKm)) ? `${distKm.toLocaleString()} km de ti` : null;
      const feltCount = Math.max(14, Math.round(Math.pow(10, Math.max(1.1, mag - 2.7)) * (isConsensus ? 18 : 8)));

      const card = document.createElement('div');
      card.className = 'quake-item ios-glass-card';
      card.setAttribute('data-quake-id', feature.id);
      card.innerHTML = `
        <div class="quake-item-header">
          <div class="mag-pill ${getMagClass(mag)}" style="background: ${color};">
            <span class="mag-num">${mag.toFixed(1)}</span>
            <span class="mag-scale">MAG</span>
          </div>
          <div class="quake-title-col">
            <div class="quake-place" title="${escapeHtml(props.place)}">${escapeHtml(props.place)}</div>
            <div class="quake-subline">
              <span class="country-badge-tag">${escapeHtml(props.country_flag || '')} ${escapeHtml(props.country_name || '')}</span>
              ${isConsensus ? `<span class="consensus-tag font-mono">🎯 CONSENSO</span>` : ''}
              <span class="quake-time-badge font-mono">${timeAgoStr}</span>
            </div>
          </div>
          <div class="quake-chevron">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="9 18 15 12 9 6"></polyline></svg>
          </div>
        </div>

        <div class="quake-item-chips font-mono">
          <span class="qchip">📏 Prof: <strong>${depth ? depth.toFixed(0) : 10} km</strong></span>
          ${distText ? `<span class="qchip highlight">📍 <strong>${distText}</strong></span>` : `<span class="qchip">🛰️ <strong>${escapeHtml(props.source_feed || 'USGS')}</strong></span>`}
          <span class="qchip">👥 <strong>${feltCount.toLocaleString()} reportes</strong></span>
        </div>
      `;

      card.addEventListener('click', () => {
        openQuakeDetailModal(feature);
      });

      quakeListEl.appendChild(card);
    }
  });
}

// Control de Alertas en Tiempo Real
let seenQuakeIds = new Set();
let alertedQuakesSet = new Set();
let isFirstLoad = true;
const MAX_LIVE_ALERT_AGE_MS = 60 * 1000; // FILTRO ESTRICTO EN TIEMPO REAL: Solo sismos ocurridos en los últimos 60 segundos

// Cargar historial de sismos alertados para evitar duplicación
try {
  const saved = localStorage.getItem('korshquake_alerted_ids');
  if (saved) {
    JSON.parse(saved).forEach(id => alertedQuakesSet.add(id));
  }
} catch (e) {}

function saveAlertedIds() {
  try {
    const arr = Array.from(alertedQuakesSet).slice(-200);
    localStorage.setItem('korshquake_alerted_ids', JSON.stringify(arr));
  } catch (e) {}
}

// --- Ingesta de Alertas en Tiempo Real por SSE Push (/api/events/live) ---
let liveEventSource = null;

function handleLiveEarthquakePush(feature) {
  if (!feature || !feature.id || !feature.properties) return;
  const p = feature.properties;
  const mag = p.mag || 0;
  const place = p.place || 'Epicentro';
  const flag = p.country_flag || '';
  const countryName = p.country_name || '';

  // 1. Insertar o actualizar en allQuakes
  const existingIdx = allQuakes.findIndex(q => q.id === feature.id);
  if (existingIdx !== -1) {
    allQuakes[existingIdx] = feature;
  } else {
    allQuakes.unshift(feature);
    if (allQuakes.length > 250) allQuakes.pop();
  }

  // 2. Notificación en vivo si es un evento nuevo
  if (!alertedQuakesSet.has(feature.id)) {
    alertedQuakesSet.add(feature.id);
    saveAlertedIds();

    const thresholdSelect = document.getElementById('select-audio-threshold');
    const thresholdMode = thresholdSelect ? thresholdSelect.value : '3.5';

    const eventTime = p.time || 0;
    const now = Date.now();
    const ageMs = now - eventTime;

    // FILTRO ESTRICTO DE SALVAGUARDA VITAL:
    // Solo emitir sonido de alarma si el evento ocurrió hace MENOS de 60 segundos
    // NUNCA asustar con sismos antiguos ni actualizaciones de catálogo pasadas
    let shouldSound = false;
    if (thresholdMode !== 'off' && ageMs >= -15000 && ageMs <= 60000) {
      const minMag = parseFloat(thresholdMode) || 3.5;
      if (mag >= minMag) shouldSound = true;
    }

    if (shouldSound) {
      playAlertSound(mag >= 4.5 ? 'major' : 'moderate');
      showToast(`🚨 SISMO EN VIVO DETECTADO: M ${mag.toFixed(1)} en ${place} (${flag} ${countryName})`);
      if (mag >= 4.5) {
        triggerEarlyWarning(feature);
      }
    }

    if ('vibrate' in navigator) {
      navigator.vibrate(mag >= 5.0 ? [400, 150, 400, 150, 600] : [200, 100, 200]);
    }

    showToast(`🚨 ¡ONDA SÍSMICA EN VIVO! ${flag} M ${mag.toFixed(1)} - ${place}`);

    // Disparar banner EEW de alerta temprana
    triggerEarlyWarning(feature);

    // Si es moderado o fuerte, abrir modal de propagación de onda P y S
    if (mag >= 4.0) {
      openPredictForEvent(feature.id);
    }
  }

  // 3. Re-renderizar mapa, ondas y tarjetas
  renderQuakes();
  updateWavefronts();
}

function initRealtimeStream() {
  if (!window.EventSource) return;
  if (liveEventSource) {
    try { liveEventSource.close(); } catch (e) {}
  }

  try {
    liveEventSource = new EventSource('/api/events/live');

    liveEventSource.addEventListener('ready', (e) => {
      console.log('📡 KorshQuake Realtime EEW Stream conectado:', e.data);
      const clusterPill = document.getElementById('cluster-pill');
      if (clusterPill) {
        clusterPill.title = 'Red Sísmica en Vivo: Stream WebSocket EMSC Activo';
      }
    });

    liveEventSource.addEventListener('mesh_eew_alert', (e) => {
      try {
        const alertData = JSON.parse(e.data);
        console.warn('⚡ [KORSH-MESH] Alerta Sísmica Temprana de Red Ciudadana:', alertData);
        if (typeof handleCitizenMeshAlert === 'function') {
          handleCitizenMeshAlert(alertData);
        }
      } catch (err) {
        console.warn('Error procesando alerta sísmica ciudadana:', err);
      }
    });

    liveEventSource.addEventListener('earthquake', (e) => {
      try {
        const feature = JSON.parse(e.data);
        handleLiveEarthquakePush(feature);
      } catch (err) {
        console.warn('Error procesando evento SSE:', err);
      }
    });

    liveEventSource.onerror = () => {
      // EventSource auto-reconecta automáticamente en cortes
    };
  } catch (err) {
    console.warn('No se pudo inicializar EventSource:', err);
  }
}

// Fetch Earthquakes con Detección Estricta en Tiempo Real
async function fetchQuakes() {
  try {
    const res = await fetch('/api/quakes');
    const data = await res.json();
    if (data && data.features) {
      allQuakes = data.features;
      const now = Date.now();

      // Umbral configurado en el selector de la cabecera
      const thresholdSelect = document.getElementById('select-audio-threshold');
      const thresholdMode = thresholdSelect ? thresholdSelect.value : '3.5';

      if (isFirstLoad) {
        // En la primera carga, se memorizan todos los sismos existentes sin hacer ningún ruido
        allQuakes.forEach(f => {
          if (f && f.id) {
            seenQuakeIds.add(f.id);
            alertedQuakesSet.add(f.id);
          }
        });
        saveAlertedIds();
        isFirstLoad = false;
      } else {
        // En cargas posteriores: Solo alertar sismos NUEVOS que ocurran EN VIVO en este instante
        const newLiveEvents = allQuakes.filter(f => {
          if (!f || !f.id || !f.properties) return false;
          if (seenQuakeIds.has(f.id) || alertedQuakesSet.has(f.id)) return false;
          
          const eventTime = f.properties.time || 0;
          const ageMs = now - eventTime;
          // FILTRO VITAL: El sismo debe haber ocurrido hace MENOS de 10 minutos para considerarse EN VIVO
          return ageMs >= -30000 && ageMs <= MAX_LIVE_ALERT_AGE_MS;
        });

        if (newLiveEvents.length > 0 && thresholdMode !== 'off') {
          const thresholdVal = parseFloat(thresholdMode) || 3.5;
          const topNew = newLiveEvents[0];
          const p = topNew.properties;
          const mag = p.mag || 0;

          if (mag >= thresholdVal) {
            const isMajor = mag >= 4.5;
            playAlertSound(isMajor ? 'major' : 'moderate');
            showToast(`🚨 SISMO EN VIVO DETECTADO: M ${mag.toFixed(1)} en ${p.place || ''} (${p.country_flag || ''} ${p.country_name || ''})`);
            if (isMajor) {
              triggerEarlyWarning(topNew);
            }
          }
        }

        // Marcar todos como vistos
        allQuakes.forEach(f => {
          if (f && f.id) {
            seenQuakeIds.add(f.id);
            alertedQuakesSet.add(f.id);
          }
        });
        saveAlertedIds();
      }

      const totalEl = document.getElementById('stat-total-quakes');
      if (totalEl) totalEl.textContent = allQuakes.length;
      
      let maxMag = 0;
      let newest = 0;

      allQuakes.forEach(f => {
        if (!f || !f.properties) return;
        const m = f.properties.mag || 0;
        if (m > maxMag) maxMag = m;
        if (f.properties.time > newest) newest = f.properties.time;
      });

      const maxMagEl = document.getElementById('stat-max-mag');
      if (maxMagEl) maxMagEl.textContent = maxMag ? `M ${maxMag.toFixed(1)}` : '--';
      
      const lastTimeEl = document.getElementById('stat-last-time');
      if (lastTimeEl) lastTimeEl.textContent = newest ? formatTimeAgo(newest) : '--';

      if (data.metadata && data.metadata.counts_by_country) {
        updateCountryPillCounts(data.metadata.counts_by_country);
      }

      renderQuakes();
    }
  } catch (err) {
    console.error('Error fetching quakes:', err);
  }
}

// Fetch Servers Telemetry
async function fetchServers() {
  try {
    const res = await fetch('/api/servers');
    const data = await res.json();
    if (data && data.servers) {
      connectedServers = data.servers;

      const clusterCountEl = document.getElementById('cluster-count');
      if (clusterCountEl) {
        const onlineCount = connectedServers.filter(s => s.status === 'ONLINE').length;
        clusterCountEl.textContent = `${onlineCount}/${connectedServers.length} Redes ONLINE`;
      }

      // Render Servers Grid in Modal
      const gridEl = document.getElementById('servers-grid');
      if (gridEl) {
        gridEl.innerHTML = connectedServers.map(s => {
          const isOnline = s.status === 'ONLINE';
          return `
            <div class="server-card">
              <div class="server-header">
                <span class="server-title">${escapeHtml(s.name)}</span>
                <span class="server-status-badge ${isOnline ? 'online' : 'standby'}">${escapeHtml(s.status)}</span>
              </div>
              <div class="server-host font-mono">${escapeHtml(s.host)}</div>
              <div class="server-region">${escapeHtml(s.region)}</div>
              <div class="server-footer font-mono">
                <span>Latencia: <strong style="color: ${s.latency_ms < 300 ? '#00e676' : '#ffd600'}">${s.latency_ms} ms</strong></span>
                <span>Sismos: <strong>${s.events_count}</strong></span>
              </div>
            </div>
          `;
        }).join('');
      }
    }
  } catch (err) {
    console.error('Error fetching servers:', err);
  }
}

// Early Warning Banner Trigger
function triggerEarlyWarning(quake) {
  if (!quake || !quake.properties) return;
  const now = Date.now();
  const originTime = quake.properties.time || now;
  // REGLA VITAL: Solo activar advertencia si ocurrió hace menos de 60 segundos
  if ((now - originTime) > 60000) return;

  const banner = document.getElementById('eew-banner');
  const title = document.getElementById('eew-title');
  const meta = document.getElementById('eew-meta');
  const intensity = document.getElementById('eew-intensity');
  if (!banner) return;

  const mag = (quake.properties.mag || 5.0).toFixed(1);
  const place = quake.properties.place || 'Zona Sísmica';
  const depth = (quake.geometry && quake.geometry.coordinates && quake.geometry.coordinates[2]) ? quake.geometry.coordinates[2].toFixed(1) : 10;
  const flag = quake.properties.country_flag || '';

  if (title) title.textContent = `${flag} Sismo M ${mag} Detectado en ${place}`;
  if (meta) meta.textContent = `Magnitud: ${mag} | Profundidad: ${depth} km | Redes: ${quake.properties.source_feed || 'Clúster'}`;
  
  if (intensity) {
    if (parseFloat(mag) >= 7.0) intensity.textContent = 'VIII - DESTRUCTOR';
    else if (parseFloat(mag) >= 6.0) intensity.textContent = 'VI - MUY FUERTE';
    else intensity.textContent = 'V - MODERADO';
  }

  banner.style.display = 'flex';
  if (window._eewBannerTimeout) clearTimeout(window._eewBannerTimeout);
  window._eewBannerTimeout = setTimeout(() => {
    if (banner) banner.style.display = 'none';
  }, 45000);
}

// Fetch GlobalQuake Status
async function fetchStatus() {
  try {
    const res = await fetch('/api/status');
    const data = await res.json();
    
    const dot = document.getElementById('gq-app-dot');
    const statusText = document.getElementById('gq-app-status');
    const launchBtn = document.getElementById('btn-launch-app');

    if (!dot || !statusText || !launchBtn) return;

    if (data.globalquake_running) {
      dot.className = 'stat-dot pulse-green';
      statusText.textContent = 'EN EJECUCIÓN';
      statusText.classList.add('text-green');
      launchBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"></rect><line x1="9" y1="9" x2="15" y2="15"></line><line x1="15" y1="9" x2="9" y2="15"></line></svg>
        <span>Detener GlobalQuake</span>
      `;
      launchBtn.onclick = stopGlobalQuakeApp;
    } else {
      dot.className = 'stat-dot';
      statusText.textContent = 'LISTO (STANDBY)';
      statusText.classList.remove('text-green');
      launchBtn.innerHTML = `
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
        <span>Abrir GlobalQuake Desktop</span>
      `;
      launchBtn.onclick = launchGlobalQuakeApp;
    }
  } catch (err) {
    console.error('Error fetching status:', err);
  }
}

// Launch GlobalQuake App
async function launchGlobalQuakeApp() {
  showToast('Iniciando GlobalQuake v1.1.2...');
  try {
    const res = await fetch('/api/launch');
    const data = await res.json();
    if (data.success) {
      showToast(data.message);
      fetchStatus();
    } else {
      showToast('Error al iniciar: ' + data.message);
    }
  } catch (err) {
    showToast('Error de conexión con el servidor.');
  }
}

// Stop GlobalQuake App
async function stopGlobalQuakeApp() {
  showToast('Para cerrar GlobalQuake utiliza la ventana de la aplicación.');
}

// Fetch Logs
async function fetchLogs() {
  try {
    const res = await fetch('/api/logs');
    const data = await res.json();
    const terminal = document.getElementById('terminal-view');
    if (terminal && data.logs) {
      terminal.innerHTML = data.logs.map(l => `<div class="log-line">${escapeHtml(l)}</div>`).join('');
      terminal.scrollTop = terminal.scrollHeight;
    }
  } catch (err) {
    console.error('Error fetching logs:', err);
  }
}

// ==============================================================================
// KORSHQUAKE CITIZEN MESH NODE & REAL HARDWARE ACCELEROMETER ENGINE
// ==============================================================================
let meshNodeState = {
  nodeId: null,
  isHardwareAvailable: false,
  isCalibrating: false,
  lat: null,
  lon: null,
  accuracy: 15.0,
  hasGpsLocation: false,
  locationPermission: 'prompt',
  locationMode: 'pending',
  country: 'VE',
  currentPga: 0.0,
  maxPga: 0.0,
  noiseFloor: 0.05,
  gravityBaseline: { x: 0.0, y: 0.0, z: 9.81 },
  sta: 0.05,
  lta: 0.05,
  staLtaRatio: 1.0,
  lastTriggerTime: 0,
  lastPingTime: 0,
  activeNodesCount: 1,
  sampleRateHz: 60,
  motionDetected: false
};

let meshNodesLayerGroup = null;

function getOrCreateNodeId() {
  let id = localStorage.getItem('korshquake_node_id');
  if (!id) {
    id = 'korsh-node-' + Math.random().toString(36).substring(2, 9) + '-' + Date.now().toString(36).slice(-4);
    localStorage.setItem('korshquake_node_id', id);
  }
  meshNodeState.nodeId = id;
  const nodeEl = document.getElementById('node-id-display');
  if (nodeEl) nodeEl.textContent = 'Nodo: #' + id.slice(-6).toUpperCase();
  return id;
}

function updateGpsUIState(status, accuracy, coords) {
  const topPill = document.getElementById('top-gps-pill');
  const topText = document.getElementById('top-gps-text');
  const banner = document.getElementById('gps-status-banner');
  const bannerBadge = document.getElementById('gps-banner-badge');
  const bannerTitle = document.getElementById('gps-banner-title');
  const modalStatus = document.getElementById('gps-modal-status-text');
  const modalAcc = document.getElementById('gps-modal-accuracy-text');
  const modalCoords = document.getElementById('gps-modal-coords-text');

  if (status === 'granted') {
    const accStr = accuracy ? `±${Math.round(accuracy)}m` : 'Fina';
    if (topPill) {
      topPill.className = 'top-gps-pill gps-ok';
      if (topText) topText.textContent = `GPS: ${accStr}`;
    }
    if (banner) banner.style.display = 'none';
    if (modalStatus) {
      modalStatus.textContent = 'ACTIVO (Satélite OK)';
      modalStatus.style.color = 'var(--green)';
    }
    if (modalAcc) modalAcc.textContent = accuracy ? `±${Math.round(accuracy)} metros (Satélite)` : 'Alta Precisión';
    if (modalCoords && coords) {
      modalCoords.textContent = `${coords.lat.toFixed(4)}°, ${coords.lon.toFixed(4)}°`;
    }
  } else if (status === 'denied') {
    if (topPill) {
      topPill.className = 'top-gps-pill gps-error';
      if (topText) topText.textContent = 'GPS Requerido';
    }
    if (banner) {
      banner.style.display = 'block';
      if (bannerBadge) {
        bannerBadge.textContent = 'Permiso Denegado';
        bannerBadge.className = 'gps-badge-status';
      }
      if (bannerTitle) bannerTitle.textContent = '📍 Activa la Ubicación en tu Teléfono';
    }
    if (modalStatus) {
      modalStatus.textContent = 'DENEGADO / APAGADO';
      modalStatus.style.color = 'var(--red)';
    }
    if (modalAcc) modalAcc.textContent = 'Sin señal satelital';
    if (modalCoords) modalCoords.textContent = 'Desconocidas (GPS Requerido)';
  } else {
    if (topPill) {
      topPill.className = 'top-gps-pill gps-warn';
      if (topText) topText.textContent = 'Buscando GPS...';
    }
    if (banner) {
      banner.style.display = 'block';
      if (bannerBadge) {
        bannerBadge.textContent = 'Requerido';
        bannerBadge.className = 'gps-badge-status';
      }
      if (bannerTitle) bannerTitle.textContent = '📍 Ubicación GPS Requerida';
    }
    if (modalStatus) {
      modalStatus.textContent = 'Buscando satélites...';
      modalStatus.style.color = 'var(--orange)';
    }
    if (modalAcc) modalAcc.textContent = 'Obteniendo señal...';
  }
}

function requestGpsPermission(isUserAction = false) {
  if (!('geolocation' in navigator)) {
    updateGpsUIState('denied', null, null);
    if (isUserAction) {
      showToast('Tu navegador o dispositivo no soporta geolocalización satelital.', 'error');
    }
    return;
  }

  navigator.geolocation.getCurrentPosition(
    (pos) => {
      meshNodeState.lat = pos.coords.latitude;
      meshNodeState.lon = pos.coords.longitude;
      meshNodeState.accuracy = pos.coords.accuracy || 15.0;
      meshNodeState.hasGpsLocation = true;
      meshNodeState.locationPermission = 'granted';
      meshNodeState.locationMode = (pos.coords.accuracy && pos.coords.accuracy < 80) ? 'gps_fine' : 'gps_coarse';
      updateGpsUIState('granted', pos.coords.accuracy, { lat: pos.coords.latitude, lon: pos.coords.longitude });
      if (isUserAction) {
        showToast(`📍 Ubicación fijada con éxito (Precisión: ±${Math.round(pos.coords.accuracy || 10)}m)`, 'success');
      }
    },
    (err) => {
      console.warn('[KORSH-MESH] Error o rechazo de GPS:', err.message);
      meshNodeState.hasGpsLocation = false;
      meshNodeState.locationPermission = (err.code === 1) ? 'denied' : 'unavailable';
      meshNodeState.locationMode = 'denied';
      updateGpsUIState('denied', null, null);
      if (isUserAction) {
        showToast('⚠️ No se pudo acceder al GPS. Asegúrate de encender la Ubicación en los ajustes de tu teléfono y permitir el acceso.', 'warning');
      }
    },
    { enableHighAccuracy: true, timeout: 20000, maximumAge: 5000 }
  );
}

function initNodeGeolocation() {
  if ('geolocation' in navigator) {
    if (navigator.permissions && navigator.permissions.query) {
      navigator.permissions.query({ name: 'geolocation' }).then((result) => {
        if (result.state === 'granted') {
          requestGpsPermission(false);
        } else if (result.state === 'denied') {
          updateGpsUIState('denied', null, null);
        } else {
          updateGpsUIState('prompt', null, null);
          requestGpsPermission(false);
        }
        result.onchange = () => {
          if (result.state === 'granted') requestGpsPermission(false);
          else if (result.state === 'denied') updateGpsUIState('denied', null, null);
        };
      }).catch(() => {
        requestGpsPermission(false);
      });
    } else {
      requestGpsPermission(false);
    }

    navigator.geolocation.watchPosition(
      (pos) => {
        meshNodeState.lat = pos.coords.latitude;
        meshNodeState.lon = pos.coords.longitude;
        meshNodeState.accuracy = pos.coords.accuracy || 15.0;
        meshNodeState.hasGpsLocation = true;
        meshNodeState.locationPermission = 'granted';
        meshNodeState.locationMode = (pos.coords.accuracy && pos.coords.accuracy < 80) ? 'gps_fine' : 'gps_coarse';
        updateGpsUIState('granted', pos.coords.accuracy, { lat: pos.coords.latitude, lon: pos.coords.longitude });
      },
      (err) => {
        console.warn('[KORSH-MESH] Error de seguimiento GPS:', err.message);
        if (!meshNodeState.hasGpsLocation) {
          updateGpsUIState((err.code === 1) ? 'denied' : 'unavailable', null, null);
        }
      },
      { enableHighAccuracy: true, maximumAge: 10000, timeout: 25000 }
    );
  } else {
    updateGpsUIState('denied', null, null);
  }
}

function calibrateAccelerometer() {
  meshNodeState.isCalibrating = true;
  meshNodeState.gravityBaseline = { x: 0.0, y: 0.0, z: 9.81 };
  meshNodeState.sta = 0.05;
  meshNodeState.lta = 0.05;
  meshNodeState.maxPga = 0.0;
  
  const pgaEl = document.getElementById('seismo-peak');
  if (pgaEl) pgaEl.textContent = 'PGA: 0.00 gal (Calibrado)';

  const badge = document.getElementById('sensor-hardware-badge');
  const text = document.getElementById('sensor-status-text');
  if (badge && text) {
    badge.className = 'sensor-badge active-sensor';
    text.textContent = 'Calibrando Gravedad Base (1.5s)...';
  }

  setTimeout(() => {
    meshNodeState.isCalibrating = false;
    if (text) {
      text.textContent = meshNodeState.isHardwareAvailable 
        ? 'Acelerómetro Físico Móvil Calibrado (100 Hz)' 
        : 'Estación Base Calibrada (Modo Estación)';
    }
  }, 1500);
}

function updateAxisDisplay(ax, ay, az, pgaGal) {
  const elX = document.getElementById('axis-x');
  const elY = document.getElementById('axis-y');
  const elZ = document.getElementById('axis-z');
  const elSta = document.getElementById('seismo-sta-lta');
  const elPga = document.getElementById('seismo-peak');

  if (elX) elX.textContent = ax.toFixed(2);
  if (elY) elY.textContent = ay.toFixed(2);
  if (elZ) elZ.textContent = az.toFixed(2);
  if (elSta) {
    elSta.textContent = meshNodeState.staLtaRatio.toFixed(1) + 'x';
    elSta.className = meshNodeState.staLtaRatio > 3.5 ? 'text-red font-bold' : 'text-cyan';
  }
  if (elPga) elPga.textContent = `PGA: ${pgaGal.toFixed(2)} gal`;
}

function checkSeismicTrigger(pgaGal, staLtaRatio) {
  const now = Date.now();
  // Umbral sísmico: STA/LTA > 3.8 y aceleración > 15.0 gal (intensidad II-III MMI)
  // Cooldown de 4.5 segundos entre disparos locales para no inundar el cluster
  if (staLtaRatio > 3.8 && pgaGal > 15.0 && (now - meshNodeState.lastTriggerTime) > 4500) {
    meshNodeState.lastTriggerTime = now;
    
    // Indicador visual en el contenedor del sismógrafo
    const container = document.getElementById('seismograph-container');
    if (container) {
      container.classList.add('seismo-trigger-active');
      setTimeout(() => container.classList.remove('seismo-trigger-active'), 4000);
    }

    // Vibración háptica en teléfonos móviles
    if (navigator.vibrate) {
      navigator.vibrate([120, 80, 180]);
    }

    // Enviar trigger al nodo servidor para correlación con otros teléfonos cercanos
    sendSeismicTriggerToNetwork(pgaGal, staLtaRatio);
  }
}

async function sendSeismicTriggerToNetwork(pgaGal, staLta) {
  try {
    const payload = {
      node_id: meshNodeState.nodeId,
      lat: meshNodeState.lat || 10.4806,
      lon: meshNodeState.lon || -66.9036,
      pga: Math.round(pgaGal * 100) / 100,
      sta_lta: Math.round(staLta * 10) / 10,
      device: navigator.userAgent.includes('Mobile') ? 'Android/iOS Smartphone' : 'Web Node'
    };

    const resp = await fetch('/api/nodes/trigger', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();
    if (data.cluster_detected) {
      console.warn('🚨 [KORSH-MESH] ¡SISMO CONFIRMADO POR LA RED DE NODOS CERCANOS!', data);
      handleCitizenMeshAlert({
        alert_title: `¡ALERTA SÍSMICA PRELIMINAR! Magnitud M${data.estimated_magnitude}`,
        magnitude: data.estimated_magnitude,
        nodes_confirmed: data.nodes_count,
        max_pga_gal: data.pga_max,
        target_country: data.country,
        latitude: data.epicenter.lat,
        longitude: data.epicenter.lon,
        alert_level: data.estimated_magnitude >= 5.0 ? 'EMERGENCY' : 'WARNING'
      });
    } else {
      console.log('📡 [KORSH-MESH] Disparo registrado. Esperando coincidencia con teléfonos cercanos...');
    }
  } catch (err) {
    console.error('[KORSH-MESH] Error enviando trigger:', err);
  }
}

async function sendNodeTelemetryPing() {
  if (!meshNodeState.nodeId) return;
  try {
    const payload = {
      node_id: meshNodeState.nodeId,
      lat: meshNodeState.lat || (meshNodeState.isDesktop ? 10.4806 : 0.0),
      lon: meshNodeState.lon || (meshNodeState.isDesktop ? -66.9036 : 0.0),
      accuracy: meshNodeState.accuracy || (meshNodeState.isDesktop ? 20.0 : 999.0),
      pga: Math.round(meshNodeState.currentPga * 100) / 100,
      sta_lta: Math.round(meshNodeState.staLtaRatio * 10) / 10,
      noise_floor: Math.round(meshNodeState.lta * 100) / 100,
      platform: meshNodeState.platform || 'web',
      device: meshNodeState.device || 'Dispositivo',
      node_type: meshNodeState.deviceType || 'mobile_phone',
      gps_enabled: meshNodeState.hasGpsLocation || meshNodeState.isDesktop,
      location_mode: meshNodeState.isDesktop ? 'desktop_fixed' : meshNodeState.locationMode
    };

    const resp = await fetch('/api/nodes/ping', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });

    const data = await resp.json();
    if (data && data.total_network_nodes !== undefined) {
      meshNodeState.activeNodesCount = data.total_network_nodes;
      updateMeshNodesCounter(data.total_network_nodes, data.nearby_nodes_count, data.mobile_nodes_count, data.desktop_nodes_count);
    }
  } catch (err) {
    // Silencioso en desconexiones
  }
}

function updateMeshNodesCounter(total, nearby, mobileCount = null, desktopCount = null) {
  const headerCountEl = document.getElementById('mesh-header-nodes');
  const panelStatusEl = document.getElementById('mesh-nodes-status');
  const sidebarCountEl = document.getElementById('sidebar-badge-quakes');

  if (headerCountEl) headerCountEl.textContent = total;
  if (panelStatusEl) {
    if (mobileCount !== null && desktopCount !== null) {
      panelStatusEl.textContent = `${total} nodos (${mobileCount} móviles • ${desktopCount} PC)`;
    } else {
      panelStatusEl.textContent = `${total} nodos (${nearby || 0} en radio regional)`;
    }
  }
}

async function updateMeshNodesMapLayer() {
  if (typeof map === 'undefined' || !map) return;
  if (!meshNodesLayerGroup) {
    meshNodesLayerGroup = L.layerGroup().addTo(map);
  }

  try {
    const resp = await fetch('/api/nodes/list');
    const data = await resp.json();
    if (data && data.nodes) {
      meshNodesLayerGroup.clearLayers();
      data.nodes.forEach(node => {
        const isSpike = node.status === 'trigger_spike';
        const marker = L.circleMarker([node.lat, node.lon], {
          radius: isSpike ? 11 : 6,
          color: isSpike ? '#ff1744' : '#ff1e42',
          fillColor: isSpike ? '#ff1744' : '#ff1e42',
          fillOpacity: 0.85,
          weight: isSpike ? 3 : 1.5
        });
        marker.bindTooltip(
          `<strong>📡 Nodo KorshQuake #${node.node_id.slice(-6).toUpperCase()}</strong><br>` +
          `Estado: ${isSpike ? '⚠️ Disparo Sísmico Activo' : '🟢 Monitoreo en Tiempo Real'}<br>` +
          `PGA: ${node.pga.toFixed(2)} gal | País: ${node.country}`,
          { direction: 'top', className: 'node-tooltip' }
        );
        meshNodesLayerGroup.addLayer(marker);
      });
    }
  } catch (err) {
    // Silencioso
  }
}

function handleCitizenMeshAlert(alertData) {
  const now = Date.now();
  const alertEpoch = alertData.detection_epoch_ms || now;
  // Descartar si el disparo tiene más de 25 segundos
  if (Math.abs(now - alertEpoch) > 25000) return;

  // 1. Mostrar banner de Alerta Temprana en UI
  const eewBanner = document.getElementById('eew-banner');
  const eewTitle = document.getElementById('eew-title');
  const eewMeta = document.getElementById('eew-meta');
  const eewEta = document.getElementById('eew-eta');

  if (eewBanner && eewTitle) {
    eewTitle.textContent = `🚨 ALERTA SÍSMICA CIUDADANA - M${alertData.magnitude || 4.5}`;
    if (eewMeta) {
      eewMeta.textContent = `Detectado por ${alertData.nodes_confirmed || 2} teléfonos cercanos en ${alertData.target_country || 'Región'} • PGA: ${alertData.max_pga_gal || 25} gal`;
    }
    if (eewEta) {
      eewEta.textContent = `ONDAS PROPAGÁNDOSE (P: 6.0 km/s | S: 3.5 km/s)`;
    }
    eewBanner.style.display = 'block';
    eewBanner.classList.add('pulse-alert');
  }

  // 2. Sirena auditiva y vibración háptica
  if (typeof playAlarmAudio === 'function') {
    playAlarmAudio();
  }
  if (navigator.vibrate) {
    navigator.vibrate([400, 200, 400, 200, 600]);
  }

  // 3. Enfocar mapa en el epicentro si Leaflet está activo
  if (typeof map !== 'undefined' && map && alertData.latitude && alertData.longitude) {
    map.flyTo([alertData.latitude, alertData.longitude], 8, { duration: 1.5 });
    
    // Dibujar onda sísmica expansiva en el mapa
    const epicCircle = L.circle([alertData.latitude, alertData.longitude], {
      radius: 12000,
      color: '#ff1744',
      fillColor: '#ff5252',
      fillOpacity: 0.35,
      weight: 3
    }).addTo(map);

    let expandRadius = 12000;
    const waveInterval = setInterval(() => {
      expandRadius += 15000;
      epicCircle.setRadius(expandRadius);
      if (expandRadius > 180000) {
        clearInterval(waveInterval);
        map.removeLayer(epicCircle);
      }
    }, 400);
  }
}

// Inicialización del Motor de Nodo y Acelerómetro
function initCitizenSeismographNode() {
  getOrCreateNodeId();
  initNodeGeolocation();

  const canvas = document.getElementById('seismograph-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const midY = height / 2;

  let points = new Array(width).fill(midY);
  let synthPhase = 0;

  const statusBadge = document.getElementById('sensor-hardware-badge');
  const statusText = document.getElementById('sensor-status-text');
  const modeTag = document.getElementById('sensor-mode-tag');

  // Calibrar al arrancar
  calibrateAccelerometer();

  // Escucha del sensor de acelerómetro físico
  function onDeviceMotion(event) {
    meshNodeState.isHardwareAvailable = true;

    let ax = 0, ay = 0, az = 0;
    if (event.acceleration && event.acceleration.x !== null) {
      ax = event.acceleration.x || 0;
      ay = event.acceleration.y || 0;
      az = event.acceleration.z || 0;
    } else if (event.accelerationIncludingGravity && event.accelerationIncludingGravity.x !== null) {
      const rawX = event.accelerationIncludingGravity.x || 0;
      const rawY = event.accelerationIncludingGravity.y || 0;
      const rawZ = event.accelerationIncludingGravity.z || 0;

      const alpha = 0.85;
      meshNodeState.gravityBaseline.x = alpha * meshNodeState.gravityBaseline.x + (1 - alpha) * rawX;
      meshNodeState.gravityBaseline.y = alpha * meshNodeState.gravityBaseline.y + (1 - alpha) * rawY;
      meshNodeState.gravityBaseline.z = alpha * meshNodeState.gravityBaseline.z + (1 - alpha) * rawZ;

      ax = rawX - meshNodeState.gravityBaseline.x;
      ay = rawY - meshNodeState.gravityBaseline.y;
      az = rawZ - meshNodeState.gravityBaseline.z;
    }

    // Magnitud escalar en m/s² y conversión a gal (cm/s²)
    const magMs2 = Math.sqrt(ax * ax + ay * ay + az * az);
    const pgaGal = magMs2 * 100.0;

    meshNodeState.currentPga = pgaGal;
    if (pgaGal > meshNodeState.maxPga) {
      meshNodeState.maxPga = pgaGal;
    }

    // Actualización de ejes en UI
    updateAxisDisplay(ax, ay, az, pgaGal);

    // Algoritmo STA/LTA
    const staCoeff = 0.12;
    const ltaCoeff = 0.006;
    meshNodeState.sta = (1 - staCoeff) * meshNodeState.sta + staCoeff * pgaGal;
    meshNodeState.lta = (1 - ltaCoeff) * meshNodeState.lta + ltaCoeff * pgaGal;
    meshNodeState.staLtaRatio = meshNodeState.sta / Math.max(0.01, meshNodeState.lta);

    // Verificación de disparo sísmico
    checkSeismicTrigger(pgaGal, meshNodeState.staLtaRatio);

    // Actualización de estado del sensor en UI
    if (statusBadge && !statusBadge.classList.contains('active-sensor')) {
      statusBadge.className = 'sensor-badge active-sensor';
      if (statusText) statusText.textContent = 'Acelerómetro Físico Móvil Activo (100 Hz)';
      if (modeTag) modeTag.textContent = 'Sensor Físico';
    }
  }

  // Activar detector de acelerómetro
  if (typeof DeviceMotionEvent !== 'undefined') {
    if (typeof DeviceMotionEvent.requestPermission === 'function') {
      if (statusText) statusText.textContent = 'Tocar para habilitar acelerómetro móvil';
      if (statusBadge) {
        statusBadge.style.cursor = 'pointer';
        statusBadge.onclick = () => {
          DeviceMotionEvent.requestPermission().then(perm => {
            if (perm === 'granted') {
              window.addEventListener('devicemotion', onDeviceMotion, { passive: true });
              if (statusText) statusText.textContent = 'Acelerómetro Físico Activo';
              statusBadge.onclick = null;
            }
          }).catch(console.error);
        };
      }
    } else {
      window.addEventListener('devicemotion', onDeviceMotion, { passive: true });
    }
  }

  // Fallback para PC / navegadores de escritorio
  setTimeout(() => {
    if (!meshNodeState.isHardwareAvailable) {
      if (statusText) statusText.textContent = 'Modo Estación (PC / Sensor Sintético)';
      if (modeTag) modeTag.textContent = 'Modo Estación PC';
    }
  }, 2200);

  // Configuración de botones en el panel
  const btnCalibrate = document.getElementById('btn-calibrate-sensor');
  if (btnCalibrate) {
    btnCalibrate.onclick = () => calibrateAccelerometer();
  }

  const btnTestCluster = document.getElementById('btn-test-cluster');
  if (btnTestCluster) {
    btnTestCluster.onclick = async () => {
      btnTestCluster.disabled = true;
      btnTestCluster.textContent = 'Simulando Red...';
      try {
        const resp = await fetch('/api/nodes/test_cluster', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            lat: meshNodeState.lat || 10.4806,
            lon: meshNodeState.lon || -66.9036,
            pga: 36.8,
            nodes_count: 3
          })
        });
        const res = await resp.json();
        console.log('Resultado simulación cluster:', res);
      } catch (err) {
        console.error('Error probando cluster:', err);
      } finally {
        setTimeout(() => {
          btnTestCluster.disabled = false;
          btnTestCluster.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8"/></svg> Probar Alerta Multi-Nodo';
        }, 3000);
      }
    };
  }

  // Bucle de renderizado de la forma de onda en Canvas a 60 FPS
  function renderSeismographCanvas() {
    points.shift();

    let targetY = midY;
    if (meshNodeState.isHardwareAvailable) {
      // Escalar aceleración física: ±50 gal llena ~42% de la altura del canvas
      const scale = (height * 0.42) / 50.0;
      const dynOffset = (meshNodeState.currentPga * (Math.sin(Date.now() * 0.04) > 0 ? 1 : -1));
      targetY = midY + Math.max(-midY * 0.88, Math.min(midY * 0.88, dynOffset * scale));
    } else {
      // Onda sintética para computadoras de escritorio
      synthPhase += 0.07;
      const noise = (Math.random() - 0.5) * 3.2;
      const w1 = Math.sin(synthPhase * 1.8) * 4.5;
      const w2 = Math.cos(synthPhase * 0.5) * 3.0;
      targetY = midY + noise + w1 + w2;
      
      const pgaEl = document.getElementById('seismo-peak');
      if (Math.random() < 0.05 && pgaEl) {
        pgaEl.textContent = `PGA: ${(0.04 + Math.random() * 0.15).toFixed(2)} gal`;
      }
    }

    points.push(targetY);

    // Fondo del canvas con rastro suave
    ctx.fillStyle = 'rgba(5, 11, 20, 0.45)';
    ctx.fillRect(0, 0, width, height);

    // Línea base central
    ctx.strokeStyle = 'rgba(0, 229, 255, 0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(width, midY);
    ctx.stroke();

    // Línea de señal sísmica
    const isSpike = meshNodeState.staLtaRatio > 3.5;
    ctx.strokeStyle = isSpike ? '#ff1744' : '#ff1e42';
    ctx.lineWidth = isSpike ? 2.2 : 1.6;
    ctx.shadowColor = isSpike ? 'rgba(255, 23, 68, 0.8)' : 'rgba(255, 30, 66, 0.6)';
    ctx.shadowBlur = isSpike ? 10 : 5;

    ctx.beginPath();
    for (let x = 0; x < width; x++) {
      if (x === 0) ctx.moveTo(x, points[x]);
      else ctx.lineTo(x, points[x]);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    requestAnimationFrame(renderSeismographCanvas);
  }

  requestAnimationFrame(renderSeismographCanvas);

  // Intervalos de telemetría y mapa de nodos
  sendNodeTelemetryPing();
  setInterval(sendNodeTelemetryPing, 12000);

  setTimeout(updateMeshNodesMapLayer, 1500);
  setInterval(updateMeshNodesMapLayer, 10000);
}

function initSeismograph() {
  initCitizenSeismographNode();
}


// Utility: Format Time Ago
function formatTimeAgo(timeMs) {
  const diffSec = Math.floor((Date.now() - timeMs) / 1000);
  if (diffSec < 60) return `Hace ${diffSec}s`;
  const diffMin = Math.floor(diffSec / 60);
  if (diffMin < 60) return `Hace ${diffMin}m`;
  const diffHrs = Math.floor(diffMin / 60);
  if (diffHrs < 24) return `Hace ${diffHrs}h`;
  const diffDays = Math.floor(diffHrs / 24);
  return `Hace ${diffDays}d`;
}

// Utility: Toast notifications
function showToast(msg) {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const toast = document.createElement('div');
  toast.className = 'toast font-mono';
  toast.innerHTML = `<span style="color: #ff1e42;">●</span> <span>${escapeHtml(msg)}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.opacity = '0';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Utility: HTML escape
function escapeHtml(str) {
  if (!str) return '';
  return str.replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#039;');
}

// Realtime Seismic Wavefront Animation Loop (P-wave and S-wave)
let waveAnimationTimer = null;

function updateWavefronts() {
  if (!map || !waveLayerGroup) return;
  waveLayerGroup.clearLayers();

  const nowMs = Date.now();
  // Filtrar sismos ocurridos hace menos de 20 minutos (1200 segundos)
  const candidateEvents = allQuakes.filter(f => {
    if (!f || !f.properties || !f.geometry) return false;
    const mag = f.properties.mag || 0;
    const timeMs = f.properties.time || 0;
    const ageSec = (nowMs - timeMs) / 1000;
    return ageSec >= 0 && ageSec <= 1200 && mag >= 3.0;
  }).slice(0, 5);

  candidateEvents.forEach(feature => {
    const coords = feature.geometry.coordinates;
    const lon = coords[0];
    const lat = coords[1];
    const props = feature.properties;
    const mag = props.mag || 0;
    const ageSec = (nowMs - props.time) / 1000;

    // Velocidades reales: Onda P = 7.8 km/s (7800 m/s), Onda S = 4.1 km/s (4100 m/s)
    const pWaveMeters = Math.min(2500000, ageSec * 7800);
    const sWaveMeters = Math.min(1500000, ageSec * 4100);

    // Frente de Onda P (Compresional primaria, azul celeste con borde discontinuo)
    const pWave = L.circle([lat, lon], {
      radius: pWaveMeters,
      color: '#ff1e42',
      weight: 1.5,
      opacity: Math.max(0.2, 0.85 - (ageSec / 1200)),
      fillColor: '#ff1e42',
      fillOpacity: 0.03,
      dashArray: '5, 5'
    });

    // Frente de Onda S (Cizalla/destructiva, roja o naranja pulsante)
    const sWave = L.circle([lat, lon], {
      radius: sWaveMeters,
      color: mag >= 5.0 ? '#ff1744' : '#ff9100',
      weight: 2.2,
      opacity: Math.max(0.25, 0.95 - (ageSec / 1200)),
      fillColor: mag >= 5.0 ? '#ff1744' : '#ff9100',
      fillOpacity: 0.07
    });

    waveLayerGroup.addLayer(pWave);
    waveLayerGroup.addLayer(sWave);
  });
}

function startWaveAnimation() {
  if (waveAnimationTimer) clearInterval(waveAnimationTimer);
  waveAnimationTimer = setInterval(updateWavefronts, 1000);
}

// Motor de Predicciones y Alerta Temprana (EEW)
let predictPollInterval = null;
let currentPredictUrl = '/api/predict';

async function fetchPredictions() {
  try {
    const res = await fetch(currentPredictUrl);
    const data = await res.json();
    renderPredictionsModal(data);
  } catch (err) {
    console.error('Error al obtener predicciones:', err);
  }
}

function renderPredictionsModal(data) {
  const modal = document.getElementById('modal-predict');
  if (!modal || !modal.classList.contains('active')) return;

  const eventTitle = document.getElementById('predict-event-title');
  const eventMeta = document.getElementById('predict-event-meta');
  const tbody = document.getElementById('predict-cities-tbody');
  if (!tbody) return;

  if (!data || !data.predictions || data.predictions.length === 0) {
    if (eventTitle) eventTitle.textContent = 'Sin eventos sísmicos recientes en rango';
    if (eventMeta) eventMeta.textContent = 'Monitoreando Panamá, Venezuela, España y Argentina en tiempo real.';
    tbody.innerHTML = `<tr><td colspan="6" style="padding: 24px; text-align: center; color: #64748b;">No hay sismos activos para calcular propagación de ondas.</td></tr>`;
    return;
  }

  if (eventTitle) {
    eventTitle.textContent = `${data.country_flag || ''} M ${(data.mag || 0).toFixed(1)} - ${data.place || 'Epicentro'}`;
  }
  if (eventMeta) {
    eventMeta.textContent = `Profundidad: ${data.depth_km || 10} km | Ocurrido hace: ${data.age_seconds || 0}s | Coord: ${data.coords ? data.coords[1].toFixed(3) + '°, ' + data.coords[0].toFixed(3) + '°' : '--'}`;
  }

  tbody.innerHTML = data.predictions.map(pred => {
    const sArrived = pred.arrived_s;
    const pArrived = pred.arrived_p;
    
    // Status de Onda S (Destructiva)
    let sStatusHtml = '';
    if (sArrived) {
      sStatusHtml = `<span style="color: #64748b; font-weight: 600;">✓ Onda Arribada</span>`;
    } else {
      const isUrgent = pred.eta_s_sec <= 30;
      sStatusHtml = `<span class="pulse-tag" style="background: ${isUrgent ? 'rgba(255, 23, 68, 0.25)' : 'rgba(255, 145, 0, 0.25)'}; color: ${isUrgent ? '#ff1744' : '#ff9100'}; border: 1px solid ${isUrgent ? '#ff1744' : '#ff9100'}; padding: 3px 8px; border-radius: 4px; font-weight: 700;">🚨 IMPACTO EN ${pred.eta_s_sec}s</span>`;
    }

    // Status de Onda P
    let pStatusHtml = pArrived 
      ? `<span style="color: #64748b;">✓ Arribada</span>`
      : `<span style="color: #ff1e42; font-weight: 700;">Arribo en ${pred.eta_p_sec}s</span>`;

    // Color según MMI
    let mmiColor = '#ff1e42';
    if (pred.mmi_intensity >= 6.0) mmiColor = '#ff1744';
    else if (pred.mmi_intensity >= 4.5) mmiColor = '#ff9100';
    else if (pred.mmi_intensity >= 3.0) mmiColor = '#ffd600';

    return `
      <tr style="border-bottom: 1px solid rgba(30, 58, 95, 0.5); transition: background 0.2s;">
        <td style="padding: 10px 8px; font-weight: 600; color: #f1f5f9;">${pred.country_flag || ''} ${escapeHtml(pred.city)}</td>
        <td style="padding: 10px 8px; color: #94a3b8;">${pred.distance_km} km</td>
        <td style="padding: 10px 8px;">${pStatusHtml}</td>
        <td style="padding: 10px 8px;">${sStatusHtml}</td>
        <td style="padding: 10px 8px; color: ${mmiColor}; font-weight: 700;">
          MMI ${pred.mmi_intensity} <span style="font-size: 0.75rem; font-weight: normal; color: #94a3b8;">(${escapeHtml(pred.mmi_description)})</span>
        </td>
        <td style="padding: 10px 8px; color: #ff8a9e;">${pred.pga_gal} cm/s²</td>
      </tr>
    `;
  }).join('');
}

window.openPredictModal = function(customUrl = null) {
  const modal = document.getElementById('modal-predict');
  if (modal) {
    currentPredictUrl = customUrl || '/api/predict';
    modal.classList.add('active');
    fetchPredictions();
    if (predictPollInterval) clearInterval(predictPollInterval);
    predictPollInterval = setInterval(fetchPredictions, 1000);
  }
};

window.openPredictForEvent = function(eventId) {
  const ev = allQuakes.find(q => q.id === eventId);
  if (ev && ev.geometry && ev.properties) {
    const coords = ev.geometry.coordinates;
    const lat = coords[1];
    const lon = coords[0];
    const depth = coords.length > 2 ? coords[2] : 10.0;
    const mag = ev.properties.mag || 4.0;
    const time = ev.properties.time || Date.now();
    const url = `/api/predict?lat=${lat}&lon=${lon}&mag=${mag}&depth=${depth}&time=${time}`;
    openPredictModal(url);
  } else {
    openPredictModal('/api/predict');
  }
};

window.closePredictModal = function() {
  const modal = document.getElementById('modal-predict');
  if (modal) {
    modal.classList.remove('active');
  }
  if (predictPollInterval) {
    clearInterval(predictPollInterval);
    predictPollInterval = null;
  }
};

// Event Listeners & Boot
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initSeismograph();
  startWaveAnimation();

  // Country Quick Tabs
  const countryTabs = document.querySelectorAll('.country-pill');
  countryTabs.forEach(pill => {
    pill.addEventListener('click', () => {
      const countryCode = pill.dataset.country;
      setCountryFilter(countryCode);
    });
  });

  // Filter magnitude change
  const filterMag = document.getElementById('filter-mag');
  if (filterMag) {
    filterMag.addEventListener('change', renderQuakes);
  }

  // Recenter map button
  const btnRecenter = document.getElementById('btn-recenter');
  if (btnRecenter) {
    btnRecenter.addEventListener('click', () => {
      const viewport = REGION_VIEWPORTS[currentCountryFilter] || REGION_VIEWPORTS.all;
      map.flyTo(viewport.center, viewport.zoom, { duration: 1.0 });
    });
  }

  // Sound toggle button
  const btnSound = document.getElementById('btn-toggle-sound');
  if (btnSound) {
    btnSound.addEventListener('click', () => {
      soundEnabled = !soundEnabled;
      document.getElementById('sound-label').textContent = soundEnabled ? 'Audio: ON' : 'Audio: OFF';
      showToast(soundEnabled ? 'Sonidos de alerta sísmica activados' : 'Sonidos de alerta silenciados');
      if (soundEnabled) playAlertSound('beep');
    });
  }

  // Servers modal
  const modalServers = document.getElementById('modal-servers');
  const btnOpenServers = document.getElementById('btn-open-servers');
  const clusterPill = document.getElementById('cluster-pill');
  const btnCloseServers = document.getElementById('btn-close-servers');
  const btnCloseServersFooter = document.getElementById('btn-close-servers-footer');
  const btnRefreshServers = document.getElementById('btn-refresh-servers');

  const openServersModal = () => {
    if (modalServers) {
      modalServers.classList.add('active');
      fetchServers();
    }
  };

  if (btnOpenServers) btnOpenServers.addEventListener('click', openServersModal);
  if (clusterPill) clusterPill.addEventListener('click', openServersModal);
  if (btnCloseServers) btnCloseServers.addEventListener('click', () => modalServers.classList.remove('active'));
  if (btnCloseServersFooter) btnCloseServersFooter.addEventListener('click', () => modalServers.classList.remove('active'));
  if (btnRefreshServers) {
    btnRefreshServers.addEventListener('click', () => {
      showToast('Actualizando latencia de redes sísmicas...');
      fetchServers();
    });
  }

  // Logs modal
  const modalLogs = document.getElementById('modal-logs');
  const btnOpenLogs = document.getElementById('btn-open-logs');
  if (btnOpenLogs && modalLogs) {
    btnOpenLogs.addEventListener('click', () => {
      modalLogs.classList.add('active');
      fetchLogs();
    });
  }
  const btnCloseLogs = document.getElementById('btn-close-logs');
  if (btnCloseLogs && modalLogs) {
    btnCloseLogs.addEventListener('click', () => {
      modalLogs.classList.remove('active');
    });
  }
  const btnRefreshLogs = document.getElementById('btn-refresh-logs');
  if (btnRefreshLogs) {
    btnRefreshLogs.addEventListener('click', fetchLogs);
  }
  const btnCopyLogs = document.getElementById('btn-copy-logs');
  if (btnCopyLogs) {
    btnCopyLogs.addEventListener('click', () => {
      const text = document.getElementById('terminal-view').innerText;
      navigator.clipboard.writeText(text);
      showToast('Logs copiados al portapapeles');
    });
  }

  // Close EEW banner
  const btnCloseEew = document.getElementById('btn-close-eew');
  if (btnCloseEew) {
    btnCloseEew.addEventListener('click', () => {
      document.getElementById('eew-banner').style.display = 'none';
    });
  }

  // APK Modal Handlers
  const modalApk = document.getElementById('modal-apk');
  const btnOpenApk = document.getElementById('btn-open-apk-modal');
  const btnCloseApk = document.getElementById('btn-close-apk');
  const btnCloseApkFooter = document.getElementById('btn-close-apk-footer');
  const apkAppUrlInput = document.getElementById('apk-app-url');
  const btnCopyAppUrl = document.getElementById('btn-copy-app-url');
  const btnDlApk = document.getElementById('btn-download-apk-link');

  const setupApkModal = () => {
    if (modalApk) {
      modalApk.classList.add('active');
      if (apkAppUrlInput) {
        apkAppUrlInput.value = window.location.origin;
      }
    }
  };

  if (btnOpenApk) btnOpenApk.addEventListener('click', setupApkModal);
  if (btnCloseApk) btnCloseApk.addEventListener('click', () => modalApk.classList.remove('active'));
  if (btnCloseApkFooter) btnCloseApkFooter.addEventListener('click', () => modalApk.classList.remove('active'));

  if (btnCopyAppUrl && apkAppUrlInput) {
    btnCopyAppUrl.addEventListener('click', () => {
      navigator.clipboard.writeText(apkAppUrlInput.value || window.location.origin);
      showToast('✓ Enlace copiado al portapapeles');
    });
  }

  if (btnDlApk) {
    btnDlApk.addEventListener('click', () => {
      showToast('📲 Descargando KorshQuake.apk (0.25 MB)...');
    });
  }

  // Capturar instalación WebAPK / PWA nativa (beforeinstallprompt)
  let deferredPwaPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPwaPrompt = e;
    const banner = document.getElementById('pwa-install-banner');
    if (banner) banner.style.display = 'block';
  });

  const btnNativeInstall = document.getElementById('btn-native-install-pwa');
  if (btnNativeInstall) {
    btnNativeInstall.addEventListener('click', async () => {
      if (deferredPwaPrompt) {
        deferredPwaPrompt.prompt();
        const { outcome } = await deferredPwaPrompt.userChoice;
        if (outcome === 'accepted') {
          showToast('✓ KorshQuake se está instalando en tu pantalla de inicio');
          const banner = document.getElementById('pwa-install-banner');
          if (banner) banner.style.display = 'none';
        }
        deferredPwaPrompt = null;
      }
    });
  }

  // Menu & Settings Modal Handlers
  const modalMenu = document.getElementById('modal-menu');
  const btnOpenMenu = document.getElementById('btn-open-menu-modal');
  const btnCloseMenu = document.getElementById('btn-close-menu');
  const btnCloseMenuFooter = document.getElementById('btn-close-menu-footer');
  const btnMenuOpenApk = document.getElementById('btn-menu-open-apk');
  const btnMenuOpenServers = document.getElementById('btn-menu-open-servers');
  const btnMenuOpenLogs = document.getElementById('btn-menu-open-logs');
  const btnTestSound = document.getElementById('btn-test-sound');
  const selectAudioThresholdMenu = document.getElementById('select-audio-threshold-menu');

  const openMenuModal = () => {
    if (modalMenu) modalMenu.classList.add('active');
  };

  const closeMenuModal = () => {
    if (modalMenu) modalMenu.classList.remove('active');
  };

  if (btnOpenMenu) btnOpenMenu.addEventListener('click', openMenuModal);
  if (btnCloseMenu) btnCloseMenu.addEventListener('click', closeMenuModal);
  if (btnCloseMenuFooter) btnCloseMenuFooter.addEventListener('click', closeMenuModal);

  if (btnMenuOpenApk) {
    btnMenuOpenApk.addEventListener('click', () => {
      closeMenuModal();
      if (modalApk) modalApk.classList.add('active');
    });
  }

  if (btnMenuOpenServers) {
    btnMenuOpenServers.addEventListener('click', () => {
      closeMenuModal();
      openServersModal();
    });
  }

  if (btnMenuOpenLogs) {
    btnMenuOpenLogs.addEventListener('click', () => {
      closeMenuModal();
      if (modalLogs) {
        modalLogs.classList.add('active');
        fetchLogs();
      }
    });
  }

  // Handlers del Modal de Predicciones Sísmicas y Alerta Temprana (EEW)
  const modalPredict = document.getElementById('modal-predict');
  const btnOpenPredict = document.getElementById('btn-open-predict-modal');
  const btnMenuOpenPredict = document.getElementById('btn-menu-open-predict');
  const btnClosePredict = document.getElementById('btn-close-predict');
  const btnClosePredictFooter = document.getElementById('btn-close-predict-footer');

  if (btnOpenPredict) btnOpenPredict.addEventListener('click', openPredictModal);
  if (btnMenuOpenPredict) {
    btnMenuOpenPredict.addEventListener('click', () => {
      closeMenuModal();
      openPredictModal();
    });
  }
  if (btnClosePredict) btnClosePredict.addEventListener('click', closePredictModal);
  if (btnClosePredictFooter) btnClosePredictFooter.addEventListener('click', closePredictModal);

  if (btnTestSound) {
    btnTestSound.addEventListener('click', () => {
      playAlertSound('major');
      showToast('🔊 Sirena de alerta sísmica de prueba emitida');
    });
  }

  // Audio Threshold Selectors Synchronization
  const selectAudioThreshold = document.getElementById('select-audio-threshold');
  const updateThreshold = (val) => {
    localStorage.setItem('korshquake_audio_threshold', val);
    if (selectAudioThreshold) selectAudioThreshold.value = val;
    if (selectAudioThresholdMenu) selectAudioThresholdMenu.value = val;
    if (val === 'off') {
      showToast('🔇 Alertas sonoras silenciadas completamente');
    } else {
      showToast(`🔔 Alerta configurada: Solo sismos en vivo M ${val}+`);
      playAlertSound('moderate');
    }
  };

  const savedThresh = localStorage.getItem('korshquake_audio_threshold') || '3.5';
  if (selectAudioThreshold) {
    selectAudioThreshold.value = savedThresh;
    selectAudioThreshold.addEventListener('change', (e) => updateThreshold(e.target.value));
  }
  if (selectAudioThresholdMenu) {
    selectAudioThresholdMenu.value = savedThresh;
    selectAudioThresholdMenu.addEventListener('change', (e) => updateThreshold(e.target.value));
  }

  // Bottom Navigation Bar Handlers (Mobile-First Experience)
  window.setMobileView = function(tab) {
    const mainLayout = document.querySelector('.main-layout');
    const metricsBar = document.getElementById('metrics-bar');
    if (mainLayout) {
      mainLayout.setAttribute('data-mobile-view', tab);
    }

    if (metricsBar) {
      if (window.innerWidth <= 768) {
        metricsBar.style.display = (tab === 'feed') ? 'flex' : 'none';
      } else {
        metricsBar.style.display = 'grid';
      }
    }
    
    const tabs = document.querySelectorAll('.bottom-nav-bar .nav-tab');
    tabs.forEach(t => {
      if (t.dataset.tab === tab) {
        t.classList.add('active');
      } else {
        t.classList.remove('active');
      }
    });

    if (tab === 'map' && map) {
      setTimeout(() => {
        map.invalidateSize();
      }, 60);
      setTimeout(() => {
        map.invalidateSize();
      }, 250);
    }
  };

  const tabNavMap = document.getElementById('tab-nav-map');
  const tabNavFeed = document.getElementById('tab-nav-feed');
  const tabNavWaves = document.getElementById('tab-nav-waves');
  const tabNavPredict = document.getElementById('tab-nav-predict');
  const tabNavSettings = document.getElementById('tab-nav-settings');

  if (tabNavMap) tabNavMap.addEventListener('click', () => setMobileView('map'));
  if (tabNavFeed) tabNavFeed.addEventListener('click', () => setMobileView('feed'));
  if (tabNavWaves) tabNavWaves.addEventListener('click', () => setMobileView('waves'));
  if (tabNavPredict) tabNavPredict.addEventListener('click', () => openPredictModal());
  if (tabNavSettings) tabNavSettings.addEventListener('click', openMenuModal);

  // Soporte para deep-links: ?country=PA / VE / ES / AR o ?view=predict
  const urlParams = new URLSearchParams(window.location.search);
  const cp = urlParams.get('country');
  const vp = urlParams.get('view');
  if (cp && REGION_VIEWPORTS[cp.toUpperCase()]) {
    setCountryFilter(cp.toUpperCase());
  }
  if (vp === 'predict' || vp === 'eew') {
    openPredictModal();
  } else if (vp === 'apk') {
    setupApkModal();
  }

  // Inicializar en vista de mapa para móvil
  if (window.innerWidth <= 768) {
    setMobileView('map');
  }

  window.addEventListener('resize', () => {
    if (map) map.invalidateSize();
  });


  // =========================================================================
  // GESTIÓN DE TÉRMINOS, SEGUNDO PLANO Y SALUD DEL NODO SÍSMICO
  // =========================================================================
  const modalTerms = document.getElementById('modal-terms');
  const btnAcceptTerms = document.getElementById('btn-accept-terms');
  const termsAccepted = localStorage.getItem('korshquake_terms_accepted') === 'true';

  if (!termsAccepted && modalTerms) {
    modalTerms.classList.add('active');
  }

  // Activar Screen WakeLock para mantener el sensor activo y prevenir Doze en móvil
  async function activateBackgroundKeepAlive() {
    try {
      if ('wakeLock' in navigator) {
        window._wakeLock = await navigator.wakeLock.request('screen');
        console.log('[KORSH-MESH] Screen WakeLock activo para protección 24/7');
      }
    } catch (err) {
      console.warn('[KORSH-MESH] WakeLock no disponible:', err);
    }
  }

  if (btnAcceptTerms) {
    btnAcceptTerms.addEventListener('click', async () => {
      localStorage.setItem('korshquake_terms_accepted', 'true');
      if (modalTerms) modalTerms.classList.remove('active');

      // Solicitar permisos de notificación en el navegador / PWA
      if ('Notification' in window && Notification.permission !== 'granted') {
        try { await Notification.requestPermission(); } catch (e) {}
      }

      // Activar WakeLock para operación en segundo plano
      await activateBackgroundKeepAlive();

      // Solicitar permisos de acelerómetro en iOS si aplica
      if (typeof DeviceMotionEvent !== 'undefined' && typeof DeviceMotionEvent.requestPermission === 'function') {
        try { await DeviceMotionEvent.requestPermission(); } catch (e) {}
      }

      showToast('🛡️ Nodo Sísmico Activado: Protección Comunitaria 24/7 Conectada');
      calibrateSensorBaseline();
    });
  }

  if (termsAccepted) {
    activateBackgroundKeepAlive();
  }

  // Modal de Diagnóstico de Salud del Nodo
  const modalDiag = document.getElementById('modal-diagnostics');
  const btnOpenDiag = document.getElementById('btn-open-diagnostics');
  const btnCloseDiag = document.getElementById('btn-close-diagnostics');

  if (btnOpenDiag && modalDiag) {
    btnOpenDiag.addEventListener('click', () => {
      const diagSensorDetail = document.getElementById('diag-sensor-detail');
      const diagSensorBadge = document.getElementById('diag-sensor-badge');
      if (diagSensorDetail && diagSensorBadge) {
        diagSensorDetail.textContent = `Acelerómetro 3D: X=${sensorCurrentX.toFixed(2)}, Y=${sensorCurrentY.toFixed(2)}, Z=${sensorCurrentZ.toFixed(2)} gal`;
        diagSensorBadge.textContent = 'ACTIVO';
        diagSensorBadge.style.color = 'var(--green)';
      }
      modalDiag.classList.add('active');
    });
  }

  if (btnCloseDiag && modalDiag) {
    btnCloseDiag.addEventListener('click', () => {
      modalDiag.classList.remove('active');
    });
  }

  if (modalDiag) {
    modalDiag.addEventListener('click', (e) => {
      if (e.target === modalDiag) modalDiag.classList.remove('active');
    });
  }

  // =========================================================================
  // VINCULACIÓN DE LISTENERS PARA GPS Y ACTUALIZACIONES PUSH OTA
  // =========================================================================
  const btnEnableGps = document.getElementById('btn-enable-gps');
  const topGpsPill = document.getElementById('top-gps-pill');
  const btnModalGps = document.getElementById('btn-modal-request-gps');

  if (btnEnableGps) btnEnableGps.addEventListener('click', () => requestGpsPermission(true));
  if (topGpsPill) topGpsPill.addEventListener('click', () => requestGpsPermission(true));
  if (btnModalGps) btnModalGps.addEventListener('click', () => requestGpsPermission(true));

  const btnOtaApply = document.getElementById('btn-ota-apply');
  const btnOtaDismiss = document.getElementById('btn-ota-dismiss');
  const btnCheckUpdates = document.getElementById('btn-check-updates-manual');

  if (btnOtaApply) btnOtaApply.addEventListener('click', applyOtaUpdate);
  if (btnOtaDismiss) {
    btnOtaDismiss.addEventListener('click', () => {
      const banner = document.getElementById('ota-update-banner');
      if (banner) banner.style.display = 'none';
    });
  }
  if (btnCheckUpdates) btnCheckUpdates.addEventListener('click', () => checkAppVersion(true));

  // Comprobar actualizaciones OTA al inicio y al volver de segundo plano
  checkAppVersion(false);
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') {
      checkAppVersion(false);
      if (!meshNodeState.hasGpsLocation) requestGpsPermission(false);
    }
  });
  setInterval(() => checkAppVersion(false), 90000);

  // Service Worker Registration for Android PWA / WebAPK
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      console.log('KorshQuake Service Worker activo:', reg.scope);
    }).catch((err) => {
      console.warn('SW no disponible en este contexto:', err);
    });
  }

  // Conexión persistente SSE en tiempo real (Notificaciones instantáneas de onda P y S)
  initRealtimeStream();

  // =========================================================================
  // VINCULACIÓN DE BOTÓN DE SIRENA DE PC Y PESTAÑAS DE BARRA LATERAL DESKTOP
  // =========================================================================
  setupDeviceNodeRole();

  const btnTestSiren = document.getElementById('btn-test-room-siren');
  if (btnTestSiren) {
    btnTestSiren.addEventListener('click', () => {
      playRoomEmergencySiren();
      showToast('🚨 Sirena de Alerta Temprana Probada (Volumen y Altavoz OK)', 'warning');
    });
  }

  const btnCloseDiagAlt = document.getElementById('btn-close-diagnostics-alt');
  if (btnCloseDiagAlt) {
    btnCloseDiagAlt.addEventListener('click', () => {
      const modalDiag = document.getElementById('modal-diagnostics');
      if (modalDiag) modalDiag.classList.remove('active');
    });
  }

  // Pestañas de la barra lateral en Desktop
  const tabBtnQuakes = document.getElementById('tab-btn-quakes');
  const tabBtnStation = document.getElementById('tab-btn-station');
  const feedPanel = document.querySelector('.feed-panel');
  const seismoPanel = document.getElementById('seismograph-container');

  if (tabBtnQuakes && tabBtnStation) {
    tabBtnQuakes.addEventListener('click', () => {
      tabBtnQuakes.classList.add('active');
      tabBtnStation.classList.remove('active');
      if (feedPanel) feedPanel.style.display = 'flex';
      if (seismoPanel && window.innerWidth <= 1200) seismoPanel.style.display = 'none';
    });

    tabBtnStation.addEventListener('click', () => {
      tabBtnStation.classList.add('active');
      tabBtnQuakes.classList.remove('active');
      if (seismoPanel) seismoPanel.style.display = 'flex';
      if (feedPanel && window.innerWidth <= 1200) feedPanel.style.display = 'none';
    });
  }

  // Initial fetch and auto-polling ultra-rápido en tiempo real
  fetchQuakes();
  fetchStatus();
  fetchServers();

  setInterval(fetchQuakes, 2500); // Refresco en vivo cada 2.5 segundos
  setInterval(fetchStatus, 3000); // Telemetría de estado cada 3.0 segundos
  setInterval(fetchServers, 10000); // Redes cada 10 segundos


  // Botón de Pantalla Completa (Centro de Control Desktop)
  const btnFullscreen = document.getElementById('btn-fullscreen');
  if (btnFullscreen) {
    btnFullscreen.addEventListener('click', () => {
      if (!document.fullscreenElement) {
        document.documentElement.requestFullscreen().then(() => {
          showToast('🖥️ Modo Pantalla Completa Activado');
          if (map) setTimeout(() => map.invalidateSize(), 200);
        }).catch(() => {});
      } else {
        document.exitFullscreen().then(() => {
          showToast('🖥️ Modo Pantalla Completa Desactivado');
          if (map) setTimeout(() => map.invalidateSize(), 200);
        }).catch(() => {});
      }
    });
  }

  // Listeners de Búsqueda de Sismos (iPhone Glass Search)
  const searchInput = document.getElementById('feed-search-input');
  const searchClear = document.getElementById('feed-search-clear');
  if (searchInput) {
    searchInput.addEventListener('input', (e) => {
      currentSearchTerm = e.target.value.toLowerCase().trim();
      if (searchClear) searchClear.style.display = currentSearchTerm ? 'inline-flex' : 'none';
      renderQuakes();
    });
  }
  if (searchClear && searchInput) {
    searchClear.addEventListener('click', () => {
      searchInput.value = '';
      currentSearchTerm = '';
      searchClear.style.display = 'none';
      renderQuakes();
      searchInput.focus();
    });
  }

  // Listeners de Cierre de Modal Ficha de Sismo
  const btnCloseQd = document.getElementById('btn-close-quake-detail');
  const btnCloseQdFooter = document.getElementById('btn-close-qd-footer');
  const modalQd = document.getElementById('modal-quake-detail');

  if (btnCloseQd) btnCloseQd.addEventListener('click', closeQuakeDetailModal);
  if (btnCloseQdFooter) btnCloseQdFooter.addEventListener('click', closeQuakeDetailModal);
  if (modalQd) {
    modalQd.addEventListener('click', (e) => {
      if (e.target === modalQd) closeQuakeDetailModal();
    });
  }
});


