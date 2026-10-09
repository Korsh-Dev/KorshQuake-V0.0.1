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
        if (window.innerWidth <= 768 && typeof setMobileView === 'function') {
          setMobileView('map');
        }
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
      color: '#00e5ff',
      weight: 1.5,
      opacity: Math.max(0.2, 0.85 - (ageSec / 1200)),
      fillColor: '#00e5ff',
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
      : `<span style="color: #00e5ff;">Arribo en ${pred.eta_p_sec}s</span>`;

    // Color según MMI
    let mmiColor = '#00e5ff';
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
        <td style="padding: 10px 8px; color: #7dd3fc;">${pred.pga_gal} cm/s²</td>
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
    if (mainLayout) {
      mainLayout.setAttribute('data-mobile-view', tab);
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
      }, 120);
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

