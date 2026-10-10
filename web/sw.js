// KorshQuake Service Worker v1.1.8 PRO
// Arquitectura OTA Push Instantánea con Network-First para código de interfaz
const CACHE_NAME = 'korshquake-v1.1.8';
const STATIC_ASSETS = [
  '/',
  '/index.html',
  '/style.css',
  '/app.js',
  '/manifest.json',
  '/vendor/leaflet/leaflet.css',
  '/vendor/leaflet/leaflet.js',
  '/vendor/plates.json',
  '/vendor/world.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
  '/icons/logo.png',
  '/favicon.ico'
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => {
      return Promise.all(
        keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
      );
    })
  );
  self.clients.claim();
});

// Soporte para comandos de actualizacion instantanea desde app.js
self.addEventListener('message', (event) => {
  if (event.data && event.data.action === 'skipWaiting') {
    self.skipWaiting();
  }
  if (event.data && event.data.action === 'clearCache') {
    caches.keys().then((keys) => {
      return Promise.all(keys.map((key) => caches.delete(key)));
    });
  }
});

self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);

  // 1. Las llamadas a /api/, descargas de APK o con cache-busters van siempre directo por red
  if (url.pathname.startsWith('/api/') || 
      url.pathname.endsWith('.apk') || 
      url.searchParams.has('_t') || 
      url.searchParams.has('_v')) {
    event.respondWith(fetch(event.request));
    return;
  }

  // 2. Network-First con fallback a cache para la aplicacion (soporta OTA sin reinstalar APK)
  if (event.request.mode === 'navigate' || 
      url.pathname.endsWith('.js') || 
      url.pathname.endsWith('.css') || 
      url.pathname === '/') {
    event.respondWith(
      fetch(event.request)
        .then((networkResponse) => {
          if (networkResponse && networkResponse.status === 200) {
            const responseClone = networkResponse.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(event.request, responseClone);
            });
          }
          return networkResponse;
        })
        .catch(() => {
          return caches.match(event.request).then((cached) => {
            return cached || caches.match('/index.html');
          });
        })
    );
    return;
  }

  // 3. Cache-First para mapas pesados GeoJSON y Leaflet
  event.respondWith(
    caches.match(event.request).then((cachedResponse) => {
      return cachedResponse || fetch(event.request).then((networkResponse) => {
        return networkResponse;
      });
    }).catch(() => {
      return caches.match('/index.html');
    })
  );
});

// ==========================================
// WebPush Event Handlers (Alertas Sísmicas Oficiales)
// ==========================================
self.addEventListener('push', (event) => {
  let data = {
    title: '⚠️ KorshQuake Alerta Sísmica',
    body: 'Movimiento telúrico instrumental detectado.',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    url: '/'
  };
  if (event.data) {
    try {
      data = Object.assign(data, event.data.json());
    } catch (e) {
      data.body = event.data.text();
    }
  }

  const options = {
    body: data.body,
    icon: data.icon || '/icons/icon-192.png',
    badge: data.badge || '/icons/icon-192.png',
    vibrate: [250, 100, 250, 100, 450],
    data: {
      url: data.url || '/'
    },
    tag: data.tag || 'korshquake-alert',
    renotify: true
  };

  event.waitUntil(
    self.registration.showNotification(data.title, options)
  );
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const targetUrl = event.notification.data && event.notification.data.url ? event.notification.data.url : '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
      for (const client of clientList) {
        if (client.url === targetUrl && 'focus' in client) {
          return client.focus();
        }
      }
      if (clients.openWindow) {
        return clients.openWindow(targetUrl);
      }
    })
  );
});
