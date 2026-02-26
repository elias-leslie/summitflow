// SummitFlow Service Worker — offline caching and PWA support

const CACHE_NAME = 'summitflow-v23'
const STATIC_CACHE_NAME = 'summitflow-static-v22'
const CACHE_PREFIX = 'summitflow-'
const CF_ACCESS_HOST = 'cloudflareaccess.com'
const ACCEPT_HTML = 'text/html'
const MSG_SKIP_WAITING = 'SKIP_WAITING'
const CACHEABLE_EXTS = ['.js', '.css', '.png']
const ICON_PATH = '/icons/icon-192.png'
const DEFAULT_NOTIF_TAG = 'summitflow-notification'
const CRITICAL_SEVERITIES = ['critical', 'error']
const OFFLINE_STATUS = 503
const STATIC_ASSETS = ['/', '/manifest.json', '/icons/icon-192.png', '/icons/icon-512.png']

// Install — cache static assets with credentials (CF Access compatible)
self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(STATIC_CACHE_NAME).then((cache) =>
      Promise.all(
        STATIC_ASSETS.map((url) =>
          fetch(url, { credentials: 'same-origin' })
            .then((res) => { if (res.ok) return cache.put(url, res) })
            .catch((err) => console.warn('SW: Failed to cache', url, err.message))
        )
      )
    )
  )
  self.skipWaiting()
})

// Activate — delete stale caches
self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((names) =>
      Promise.all(
        names
          .filter((n) => n.startsWith(CACHE_PREFIX) && n !== CACHE_NAME && n !== STATIC_CACHE_NAME)
          .map((n) => caches.delete(n))
      )
    )
  )
  self.clients.claim()
})

self.addEventListener('message', (event) => {
  if (event.data?.type === MSG_SKIP_WAITING) self.skipWaiting()
})

// ============================================================================
// Fetch helpers
// ============================================================================

function isCfAccessRedirect(res) {
  return res.redirected && res.url.includes(CF_ACCESS_HOST)
}

function isCacheableAsset(pathname) {
  return CACHEABLE_EXTS.some((ext) => pathname.endsWith(ext))
}

function storeInCache(cacheName, request, response) {
  caches.open(cacheName).then((cache) => cache.put(request, response))
}

function networkFirstHtml(request) {
  return fetch(request, { credentials: 'same-origin' })
    .then((res) => {
      if (res.ok) storeInCache(CACHE_NAME, request, res.clone())
      return res
    })
    .catch(() => caches.match(request).then((cached) => cached || caches.match('/')))
}

function cacheFirstAsset(request, url) {
  return caches.match(request).then((cached) => {
    if (cached) {
      fetch(request, { credentials: 'same-origin' })
        .then((res) => { if (!isCfAccessRedirect(res) && res.ok) storeInCache(CACHE_NAME, request, res) })
        .catch(() => {})
      return cached
    }
    return fetch(request, { credentials: 'same-origin' })
      .then((res) => {
        if (isCfAccessRedirect(res)) return res
        if (res.ok && isCacheableAsset(url.pathname)) storeInCache(CACHE_NAME, request, res.clone())
        return res
      })
      .catch((err) => {
        console.warn('Service worker fetch failed:', url.pathname, err.message)
        return new Response('Offline', { status: OFFLINE_STATUS, statusText: 'Service Unavailable' })
      })
  })
}

// Fetch — network-first for HTML, cache-first for static assets
self.addEventListener('fetch', (event) => {
  const { request } = event
  const url = new URL(request.url)
  if (request.method !== 'GET') return
  if (url.pathname.startsWith('/api/') || url.pathname.startsWith('/ws/')) return
  if (url.protocol === 'ws:' || url.protocol === 'wss:') return
  if (request.headers.get('accept')?.includes(ACCEPT_HTML)) {
    event.respondWith(networkFirstHtml(request))
    return
  }
  event.respondWith(cacheFirstAsset(request, url))
})

// ============================================================================
// Push notifications
// ============================================================================

self.addEventListener('push', (event) => {
  if (!event.data) return
  let data
  try { data = event.data.json() } catch { data = { title: 'SummitFlow', body: event.data.text() } }
  event.waitUntil(
    self.registration.showNotification(data.title || 'SummitFlow', {
      body: data.body || '',
      icon: ICON_PATH,
      badge: ICON_PATH,
      tag: data.tag || DEFAULT_NOTIF_TAG,
      renotify: true,
      requireInteraction: CRITICAL_SEVERITIES.includes(data.severity),
      vibrate: [200, 100, 200],
      data: { url: data.url || '/', task_id: data.task_id || null, notification_id: data.notification_id || null },
      actions: data.task_id ? [{ action: 'view', title: 'View Task' }] : [],
    })
  )
})

self.addEventListener('notificationclick', (event) => {
  event.notification.close()
  const url = event.notification.data?.url || '/'
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then((windowClients) => {
      for (const client of windowClients) {
        if ('focus' in client) { client.focus(); client.navigate(url); return }
      }
      return clients.openWindow(url)
    })
  )
})
