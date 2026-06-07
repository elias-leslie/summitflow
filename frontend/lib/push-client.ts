import { getAgentHubProxyBase } from './agent-hub-proxy'

type VapidKeyResponse = {
  public_key?: string
}

function getPushApiBase(): string {
  return `${getAgentHubProxyBase()}/push`
}

function getNotificationPermission(): NotificationPermission {
  if (typeof window === 'undefined' || !('Notification' in window)) {
    return 'denied'
  }
  return Notification.permission
}

function urlBase64ToArrayBuffer(base64String: string): ArrayBuffer {
  const padding = '='.repeat((4 - (base64String.length % 4)) % 4)
  const base64 = `${base64String}${padding}`
    .replaceAll('-', '+')
    .replaceAll('_', '/')
  const rawData = window.atob(base64)
  const buffer = new ArrayBuffer(rawData.length)
  const outputArray = new Uint8Array(buffer)
  for (let i = 0; i < rawData.length; i += 1) {
    outputArray[i] = rawData.charCodeAt(i)
  }
  return buffer
}

async function getCurrentSubscription(): Promise<PushSubscription | null> {
  if (!isPushSupported()) return null
  const registration = await navigator.serviceWorker.ready
  return registration.pushManager.getSubscription()
}

async function fetchVapidPublicKey(): Promise<string | null> {
  const response = await fetch(`${getPushApiBase()}/vapid-key`)
  if (!response.ok) return null

  const data = (await response.json()) as VapidKeyResponse
  return data.public_key || null
}

export function isPushSupported(): boolean {
  return (
    typeof window !== 'undefined' &&
    'Notification' in window &&
    'serviceWorker' in navigator &&
    'PushManager' in window
  )
}

export function getPermissionState(): NotificationPermission {
  return getNotificationPermission()
}

export async function isSubscribed(): Promise<boolean> {
  return (await getCurrentSubscription()) !== null
}

export async function subscribe(): Promise<boolean> {
  if (!isPushSupported()) return false

  const permission =
    getNotificationPermission() === 'default'
      ? await Notification.requestPermission()
      : getNotificationPermission()
  if (permission !== 'granted') return false

  const publicKey = await fetchVapidPublicKey()
  if (!publicKey) return false

  const registration = await navigator.serviceWorker.ready
  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: urlBase64ToArrayBuffer(publicKey),
  })

  const response = await fetch(`${getPushApiBase()}/subscriptions`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(subscription.toJSON()),
  })

  if (!response.ok) {
    await subscription.unsubscribe().catch(() => undefined)
    return false
  }

  return true
}

export async function unsubscribe(): Promise<boolean> {
  const subscription = await getCurrentSubscription()
  if (!subscription) return true

  const localUnsubscribed = await subscription.unsubscribe()
  const response = await fetch(`${getPushApiBase()}/subscriptions`, {
    method: 'DELETE',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ endpoint: subscription.endpoint }),
  })

  return localUnsubscribed && (response.ok || response.status === 404)
}
