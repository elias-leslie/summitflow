// SummitFlow Service Worker
// Provides offline caching and PWA support

const CACHE_NAME = 'summitflow-v23';
const STATIC_CACHE_NAME = 'summitflow-static-v22';

// Static assets to cache on install
const STATIC_ASSETS = [
  '/',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png',
];

// Install event - cache static assets
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME).then((cache) => {
      // Fetch with credentials to work with CF Access
      // Use individual fetches instead of cache.addAll to include credentials
      return Promise.all(
        STATIC_ASSETS.map((url) =>
          fetch(url, { credentials: 'same-origin' })
            .then((response) => {
              if (response.ok) {
                return cache.put(url, response);
              }
              // Skip caching if fetch failed (e.g., CF Access redirect)
              console.warn('SW: Skipping cache for', url, response.status);
            })
            .catch((err) => {
              // Silently skip assets that fail to fetch
              console.warn('SW: Failed to cache', url, err.message);
            })
        )
      );
    })
  );
  // Activate immediately
  self.skipWaiting();
});

// Activate event - clean up old caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      return Promise.all(
        cacheNames
          .filter((name) => name.startsWith('summitflow-') && name !== CACHE_NAME && name !== STATIC_CACHE_NAME)
          .map((name) => caches.delete(name))
      );
    })
  );
  // Take control of all clients
  self.clients.claim();
});

// Fetch event - network first with cache fallback
self.addEventListener('fetch', (event) => {
  const { request } = event;
  const url = new URL(request.url);

  // Skip non-GET requests
  if (request.method !== 'GET') {
    return;
  }

  // Skip API and WebSocket requests - always go to network
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) {
    return;
  }

  // Skip WebSocket connections
  if (url.protocol === 'ws:' || url.protocol === 'wss:') {
    return;
  }

  // Network first strategy for HTML pages
  if (request.headers.get('accept')?.includes('text/html')) {
    event.respondWith(
      fetch(request, { credentials: 'same-origin' })
        .then((response) => {
          // Clone and cache successful responses
          if (response.ok) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch(() => {
          // Fall back to cache
          return caches.match(request).then((cached) => {
            return cached || caches.match('/');
          });
        })
    );
    return;
  }

  // Cache first strategy for static assets
  event.respondWith(
    caches.match(request).then((cached) => {
      if (cached) {
        // Return cached and update in background with credentials for CF Access
        fetch(request, { credentials: 'same-origin' })
          .then((response) => {
            // Skip caching if redirected to CF Access (CORS issue)
            if (response.redirected && response.url.includes('cloudflareaccess.com')) {
              return;
            }
            if (response.ok) {
              caches.open(CACHE_NAME).then((cache) => {
                cache.put(request, response);
              });
            }
          })
          .catch(() => {
            // Silently ignore fetch errors during background updates
          });
        return cached;
      }

      // Not in cache - fetch from network with credentials for CF Access
      return fetch(request, { credentials: 'same-origin' })
        .then((response) => {
          // Skip caching if redirected to CF Access
          if (response.redirected && response.url.includes('cloudflareaccess.com')) {
            return response;
          }
          // Cache successful responses for static assets
          if (response.ok && (url.pathname.endsWith('.js') || url.pathname.endsWith('.css') || url.pathname.endsWith('.png'))) {
            const responseClone = response.clone();
            caches.open(CACHE_NAME).then((cache) => {
              cache.put(request, responseClone);
            });
          }
          return response;
        })
        .catch((error) => {
          // If fetch fails (e.g., CF Access CORS), return offline fallback
          console.warn('Service worker fetch failed:', url.pathname, error.message);
          return new Response('Offline', { status: 503, statusText: 'Service Unavailable' });
        });
    })
  );
});

// Message handler for cache control
self.addEventListener('message', (event) => {
  if (event.data && event.data.type === 'SKIP_WAITING') {
    self.skipWaiting();
  }
});

// ============================================================================
// Push Notification Handlers
// ============================================================================

// Handle incoming push notifications
self.addEventListener('push', (event) => {
  if (!event.data) return;

  let data;
  try {
    data = event.data.json();
  } catch {
    data = { title: 'SummitFlow', body: event.data.text() };
  }

  const options = {
    body: data.body || '',
    icon: '/icons/icon-192.png',
    badge: '/icons/icon-192.png',
    tag: data.tag || 'summitflow-notification',
    renotify: true,
    requireInteraction: data.severity === 'critical' || data.severity === 'error',
    vibrate: [200, 100, 200],
    data: {
      url: data.url || '/',
      task_id: data.task_id || null,
      notification_id: data.notification_id || null,
    },
    actions: data.task_id
      ? [{ action: 'view', title: 'View Task' }]
      : [],
  };

  event.waitUntil(
    self.registration.showNotification(data.title || 'SummitFlow', options)
  );
});

// Handle notification click — open/focus PWA and navigate to task
self.addEventListener('notificationclick', (event) => {
  event.notification.close();

  const url = event.notification.data?.url || '/';

  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      // If PWA is already open, focus it and navigate
      for (const client of windowClients) {
        if ('focus' in client) {
          client.focus();
          client.navigate(url);
          return;
        }
      }
      // Otherwise open a new window
      return clients.openWindow(url);
    })
  );
});
