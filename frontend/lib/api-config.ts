/**
 * API configuration for SummitFlow frontend.
 *
 * Provides consistent URL resolution for:
 * - Development (localhost:8001)
 * - Production (devapi.summitflow.dev)
 *
 * This pattern is self-contained - no external dependencies required.
 */

const PORTS = { frontend: 3001, backend: 8001 }
const PROD_DOMAIN = 'dev.summitflow.dev'
const PROD_API_DOMAIN = 'devapi.summitflow.dev'

/**
 * Get the base URL for SummitFlow backend API calls.
 *
 * @returns Full URL (e.g., http://localhost:8001 or https://devapi.summitflow.dev)
 */
export function getApiBaseUrl(): string {
  // Server-side: always use localhost
  if (typeof window === 'undefined') {
    return `http://localhost:${PORTS.backend}`
  }

  const host = window.location.hostname

  // Development: localhost or 127.0.0.1
  if (host === 'localhost' || host === '127.0.0.1') {
    return `http://localhost:${PORTS.backend}`
  }

  // Production: use same-origin to avoid CF Access CORS issues
  // Next.js rewrites /api/* to backend, so we don't need cross-origin URL
  if (host === PROD_DOMAIN) {
    return '' // Empty string = same-origin (uses current domain)
  }

  // Fallback: use localhost (shouldn't happen in normal use)
  return `http://localhost:${PORTS.backend}`
}

/**
 * Get WebSocket URL for a given path.
 *
 * IMPORTANT: WebSockets connect directly to the API domain (devapi.summitflow.dev)
 * not the frontend domain. This is because:
 * 1. Next.js rewrites don't work for WebSocket connections
 * 2. CF Tunnel supports WebSocket passthrough to the API backend
 *
 * @param path - WebSocket path (e.g., /ws/execution/task-123)
 * @returns Full WebSocket URL
 */
export function getWsUrl(path: string): string {
  if (typeof window === 'undefined') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  const host = window.location.hostname

  // Development: use localhost
  if (host === 'localhost' || host === '127.0.0.1') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  // Production: connect directly to API domain for WebSocket
  // CF Tunnel routes devapi.summitflow.dev -> localhost:8001
  if (host === PROD_DOMAIN) {
    return `wss://${PROD_API_DOMAIN}${path}`
  }

  // Fallback
  return `ws://localhost:${PORTS.backend}${path}`
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
 * Uses same-origin routing in production to avoid CF Access cookie issues:
 * Browser → wss://dev.summitflow.dev/api/voice/ws → CF tunnel → Next.js → rewrite → Agent Hub
 */
export function getVoiceWsUrl(): string | null {
  const voiceUrl = process.env.NEXT_PUBLIC_VOICE_URL
  if (voiceUrl) return voiceUrl

  if (typeof window === 'undefined') return null

  const host = window.location.hostname
  const params = 'user_id=summitflow_user&app=summitflow&mode=transcribe'

  // Development: direct to Agent Hub backend
  if (host === 'localhost' || host === '127.0.0.1') {
    return `ws://localhost:8003/api/voice/ws?${params}`
  }

  // Production: same-origin WebSocket via CF tunnel + Next.js rewrite
  if (host === PROD_DOMAIN) {
    return `wss://${PROD_DOMAIN}/api/voice/ws?${params}`
  }

  return null
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

  const host = window.location.hostname

  // Development: direct to Agent Hub backend
  if (host === 'localhost' || host === '127.0.0.1') {
    return 'http://localhost:8003'
  }

  // Production: same-origin (rewrite proxies /api/voice/tts to Agent Hub)
  // Return explicit origin — useVoice checks !ttsBaseUrl, and '' is falsy
  if (host === PROD_DOMAIN) {
    return window.location.origin
  }

  return null
}
