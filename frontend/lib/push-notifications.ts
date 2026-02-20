/**
 * Web Push notification subscription management.
 *
 * Handles browser permission, PushManager subscription,
 * and syncing subscriptions with the backend.
 */

/**
 * Check if push notifications are supported in this browser.
 */
export function isPushSupported(): boolean {
  return (
    'serviceWorker' in navigator &&
    'PushManager' in window &&
    'Notification' in window
  )
}

/**
 * Get the current notification permission state.
 */
export function getPermissionState(): NotificationPermission {
  if (!isPushSupported()) return 'denied'
  return Notification.permission
}

/**
 * Check if the user is currently subscribed to push notifications.
 */
export async function isSubscribed(): Promise<boolean> {
  if (!isPushSupported()) return false

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.getSubscription()
  return subscription !== null
}

/**
 * Fetch the VAPID public key from Agent Hub push service.
 */
async function fetchVapidKey(): Promise<string> {
  const res = await fetch('/api/agent-hub/push/vapid-key')
  if (!res.ok) throw new Error('Failed to fetch VAPID key')
  const data = await res.json()
  return data.public_key
}

/**
 * Convert a base64 URL-safe string to a Uint8Array.
 * Required by PushManager.subscribe() for applicationServerKey.
 */
function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = (base64String + padding).replace(/-/g, '+').replace(/_/g, '/')
  const rawData = window.atob(base64)
  const outputArray = new Uint8Array(rawData.length)
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return outputArray
}

/**
 * Subscribe to push notifications.
 *
 * Requests permission, subscribes via PushManager, and saves
 * the subscription to the backend.
 *
 * Returns true if subscribed successfully.
 */
export async function subscribe(): Promise<boolean> {
  if (!isPushSupported()) return false

  // Request permission
  const permission = await Notification.requestPermission()
  if (permission !== 'granted') {
    console.warn('[push] Permission not granted:', permission)
    return false
  }

  try {
    // Ensure SW is registered (may have been cleared)
    console.log('[push] Ensuring service worker is registered...')
    let registration = await navigator.serviceWorker.getRegistration()
    if (!registration) {
      console.log('[push] No SW found, registering...')
      registration = await navigator.serviceWorker.register('/sw.js?v=23')
      await navigator.serviceWorker.ready
    }

    console.log('[push] Fetching VAPID key...')
    const vapidKey = await fetchVapidKey()

    console.log('[push] Subscribing via PushManager...')
    const subscription = await registration.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: urlBase64ToUint8Array(vapidKey).buffer as ArrayBuffer,
    })

    console.log('[push] PushManager subscribed, saving to Agent Hub...')
    const subJson = subscription.toJSON()
    const res = await fetch('/api/agent-hub/push/subscriptions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        endpoint: subJson.endpoint,
        keys: {
          p256dh: subJson.keys?.p256dh ?? '',
          auth: subJson.keys?.auth ?? '',
        },
      }),
    })

    console.log('[push] Backend response:', res.status)
    return res.ok
  } catch (err) {
    console.error('[push] Subscription failed:', err)
    return false
  }
}

/**
 * Unsubscribe from push notifications.
 *
 * Unsubscribes from PushManager and removes subscription from backend.
 *
 * Returns true if unsubscribed successfully.
 */
export async function unsubscribe(): Promise<boolean> {
  if (!isPushSupported()) return false

  try {
    const registration = await navigator.serviceWorker.ready
    const subscription = await registration.pushManager.getSubscription()

    if (subscription) {
      // Remove from Agent Hub
      await fetch('/api/agent-hub/push/subscriptions', {
        method: 'DELETE',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ endpoint: subscription.endpoint }),
      })

      // Unsubscribe from browser
      await subscription.unsubscribe()
    }

    return true
  } catch (err) {
    console.error('Push unsubscribe failed:', err)
    return false
  }
}
