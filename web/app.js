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
          fillColor: '#0a1626',
          fillOpacity: 0.25,
          color: '#1a3350',
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
  return '#00e5ff';
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
      </div>
    `;
    marker.bindPopup(popupHtml);
    quakeLayerGroup.addLayer(marker);

    // Ondas P y S para eventos mayores (< 45 min)
    const ageSeconds = (nowMs - props.time) / 1000;
    if (ageSeconds > 0 && ageSeconds < 2700 && mag >= 4.5 && idx < 6) {
      const pWaveMeters = Math.min(1200000, ageSeconds * 7800);
      const sWaveMeters = Math.min(650000, ageSeconds * 4200);

      const pWave = L.circle([lat, lon], {
        radius: pWaveMeters,
        color: '#2979ff',
        weight: 1.5,
        opacity: 0.7,
        fillColor: '#2979ff',
        fillOpacity: 0.05,
        dashArray: '4, 4'
      });
      const sWave = L.circle([lat, lon], {
        radius: sWaveMeters,
        color: '#ff1744',
        weight: 2,
        opacity: 0.85,
        fillColor: '#ff1744',
        fillOpacity: 0.08
      });
      waveLayerGroup.addLayer(pWave);
      waveLayerGroup.addLayer(sWave);
    }

    // Tarjeta en Sidebar
    if (quakeListEl) {
      const card = document.createElement('div');
      card.className = 'quake-item';
      card.innerHTML = `
        <div class="quake-left">
          <div class="mag-pill ${getMagClass(mag)}">
            <span>${mag.toFixed(1)}</span>
            <span class="mag-scale">MAG</span>
          </div>
          <div class="quake-info">
            <div class="quake-place" title="${escapeHtml(props.place)}">${escapeHtml(props.place)}</div>
            <div class="quake-meta font-mono">
              ${escapeHtml(props.source_feed || 'USGS')} • Prof: ${depth ? depth.toFixed(0) : 10} km
            </div>
            <div>
              <span class="country-badge-tag">${escapeHtml(props.country_flag || '')} ${escapeHtml(props.country_name || '')}</span>
              ${isConsensus ? `<span class="consensus-tag font-mono" style="margin-left: 6px;">🎯 CONSENSO</span>` : ''}
            </div>
          </div>
        </div>
        <div class="quake-right font-mono">
          <span class="quake-time-ago">${timeAgoStr}</span>
          <span class="quake-depth">${(lat > 0 ? lat.toFixed(1) + '°N' : Math.abs(lat).toFixed(1) + '°S')}</span>
        </div>
      `;

      card.addEventListener('click', () => {
        map.flyTo([lat, lon], 6.5, { duration: 1.2 });
        marker.openPopup();
      });

      quakeListEl.appendChild(card);
    }
  });
}

// Control de Alertas en Tiempo Real
let seenQuakeIds = new Set();
let alertedQuakesSet = new Set();
let isFirstLoad = true;
const MAX_LIVE_ALERT_AGE_MS = 10 * 60 * 1000; // Solo sismos ocurridos en los últimos 10 minutos (EN VIVO)

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

// Realtime Synthetic Seismograph Waveform Simulation
function initSeismograph() {
  const canvas = document.getElementById('seismograph-canvas');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const width = canvas.width;
  const height = canvas.height;
  const midY = height / 2;

  let points = new Array(width).fill(midY);
  let phase = 0;
  let pgaEl = document.getElementById('seismo-peak');

  function renderWave() {
    points.shift();
    phase += 0.07;
    
    // Waveform simulation
    let noise = (Math.random() - 0.5) * 4.5;
    let wave1 = Math.sin(phase * 1.8) * 6.5;
    let wave2 = Math.sin(phase * 4.2) * 3.5;
    let wave3 = Math.cos(phase * 0.4) * 8.0;

    let y = midY + noise + wave1 + wave2 + wave3;
    points.push(y);

    if (Math.random() < 0.05 && pgaEl) {
      let currentPga = (0.05 + Math.random() * 0.28).toFixed(2);
      pgaEl.textContent = `PGA: ${currentPga} cm/s²`;
    }

    ctx.fillStyle = 'rgba(5, 11, 20, 0.45)';
    ctx.fillRect(0, 0, width, height);

    ctx.strokeStyle = 'rgba(0, 229, 255, 0.15)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, midY);
    ctx.lineTo(width, midY);
    ctx.stroke();

    ctx.strokeStyle = '#00e5ff';
    ctx.lineWidth = 1.6;
    ctx.shadowColor = 'rgba(0, 229, 255, 0.5)';
    ctx.shadowBlur = 6;
    ctx.beginPath();
    for (let x = 0; x < width; x++) {
      if (x === 0) ctx.moveTo(x, points[x]);
      else ctx.lineTo(x, points[x]);
    }
    ctx.stroke();
    ctx.shadowBlur = 0;

    requestAnimationFrame(renderWave);
  }

  requestAnimationFrame(renderWave);
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
  toast.innerHTML = `<span style="color: #00e5ff;">●</span> <span>${escapeHtml(msg)}</span>`;
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

// Event Listeners & Boot
document.addEventListener('DOMContentLoaded', () => {
  initMap();
  initSeismograph();

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

  if (btnOpenApk && modalApk) {
    btnOpenApk.addEventListener('click', () => modalApk.classList.add('active'));
  }
  if (btnCloseApk && modalApk) {
    btnCloseApk.addEventListener('click', () => modalApk.classList.remove('active'));
  }
  if (btnCloseApkFooter && modalApk) {
    btnCloseApkFooter.addEventListener('click', () => modalApk.classList.remove('active'));
  }

  // Audio Threshold Selector
  const selectAudioThreshold = document.getElementById('select-audio-threshold');
  if (selectAudioThreshold) {
    const savedThresh = localStorage.getItem('korshquake_audio_threshold');
    if (savedThresh) selectAudioThreshold.value = savedThresh;
    selectAudioThreshold.addEventListener('change', (e) => {
      localStorage.setItem('korshquake_audio_threshold', e.target.value);
      if (e.target.value === 'off') {
        showToast('🔇 Alertas sonoras silenciadas completamente');
      } else {
        showToast(`🔔 Alerta configurada: Solo sismos en vivo M ${e.target.value}+`);
        playAlertSound('moderate');
      }
    });
  }

  // Service Worker Registration for Android PWA / WebAPK
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js').then((reg) => {
      console.log('KorshQuake Service Worker activo:', reg.scope);
    }).catch((err) => {
      console.warn('SW no disponible en este contexto:', err);
    });
  }

  // Initial fetch and auto-polling ultra-rápido en tiempo real
  fetchQuakes();
  fetchStatus();
  fetchServers();

  setInterval(fetchQuakes, 2500); // Refresco en vivo cada 2.5 segundos
  setInterval(fetchStatus, 3000); // Telemetría de estado cada 3.0 segundos
  setInterval(fetchServers, 10000); // Redes cada 10 segundos
});

