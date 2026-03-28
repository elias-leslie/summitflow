/**
 * API configuration for SummitFlow frontend.
 *
 * Provides consistent URL resolution for:
 * - Development on localhost (direct backend access)
 * - Any deployed or LAN host (same-origin via Next.js rewrites)
 *
 * This pattern is self-contained - no external dependencies required.
 */

export const PORTS = { frontend: 3001, backend: 8001, agentHub: 8003 }

function isLocalDev(): boolean {
  if (typeof window === 'undefined') return false
  const host = window.location.hostname
  return host === 'localhost' || host === '127.0.0.1'
}

/**
 * Get the base URL for SummitFlow backend API calls.
 *
 * @returns Full URL (e.g., http://localhost:8001) or same-origin base ('')
 */
export function getApiBaseUrl(): string {
  // Server-side: use API_URL env var (set by Docker compose) or localhost fallback
  if (typeof window === 'undefined') {
    return process.env.API_URL || `http://localhost:${PORTS.backend}`
  }

  // Development: localhost or 127.0.0.1
  if (isLocalDev()) {
    return `http://localhost:${PORTS.backend}`
  }

  // Any non-local browser host should stay same-origin via rewrites.
  return ''
}

/**
 * Get WebSocket URL for a given path.
 *
 * Non-local browser hosts use the current origin so CF Access cookies stay
 * same-origin for both tunnel and LAN/Caddy access.
 *
 * @param path - WebSocket path (e.g., /ws/execution/task-123)
 * @returns Full WebSocket URL
 */
export function getWsUrl(path: string): string {
  if (typeof window === 'undefined') {
    const apiUrl = process.env.API_URL || `http://localhost:${PORTS.backend}`
    return apiUrl.replace(/^http/, 'ws') + path
  }

  // Development: use localhost
  if (isLocalDev()) {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  // Any non-local browser host should stay same-origin via rewrites.
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}${path}`
}

/**
 * Build a full API URL from a path.
 *
 * @param path - API path (e.g., /api/tasks)
 * @returns Full URL
 */
export function buildApiUrl(path: string): string {
  return `${getApiBaseUrl()}${path}`
}

/** Centralized API endpoint paths (relative — resolved via buildApiUrl at call site). */
export const API_PATHS = {
  HEALTH_DETAILED: '/api/health/detailed',
} as const

/**
 * Get Agent Hub voice WebSocket URL.
 * Returns null server-side (voice is client-only).
 *
 * Uses same-origin routing on any non-local browser host to avoid CF Access
 * cookie issues and to keep LAN access working without a second API hostname.
 */
export function getVoiceWsUrl(): string | null {
  const voiceUrl = process.env.NEXT_PUBLIC_VOICE_URL
  if (voiceUrl) return voiceUrl

  if (typeof window === 'undefined') return null

  const params = 'user_id=summitflow_user&app=summitflow&mode=transcribe'

  // Development: direct to Agent Hub backend
  if (isLocalDev()) {
    return `ws://localhost:${PORTS.agentHub}/api/voice/ws?${params}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/api/voice/ws?${params}`
}

/**
 * Get Agent Hub TTS base URL for text-to-speech.
 * Used by ChatPanel for voice responses.
 * Returns the origin only — useVoice appends /api/voice/tts.
 *
 * Same-origin in production: Next.js rewrite proxies /api/voice/* to Agent Hub.
 */
export function getTtsBaseUrl(): string | null {
  if (typeof window === 'undefined') return null

  // Development: direct to Agent Hub backend
  if (isLocalDev()) {
    return `http://localhost:${PORTS.agentHub}`
  }

  // Any non-local browser host stays same-origin via rewrites.
  return window.location.origin
}
