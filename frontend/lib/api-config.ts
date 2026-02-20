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

/**
 * Get Agent Hub voice WebSocket URL (external service).
 * Returns null if not configured (feature disabled).
 *
 * Voice is provided by agent-hub, which may or may not be available.
 */
export function getVoiceWsUrl(): string | null {
  // Check if voice is configured via env var
  const voiceUrl = process.env.NEXT_PUBLIC_VOICE_URL
  if (voiceUrl) {
    return voiceUrl
  }

  // In development, try to connect to local agent-hub
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'ws://localhost:8003/api/voice/ws?user_id=summitflow_user&app=summitflow'
    }
    // Production: use agent-hub production URL
    if (host === PROD_DOMAIN) {
      return 'wss://agentapi.summitflow.dev/api/voice/ws?user_id=summitflow_user&app=summitflow'
    }
  }

  return null
}

/**
 * Get Agent Hub TTS base URL for text-to-speech.
 * Used by ChatPanel for voice responses.
 */
export function getTtsBaseUrl(): string | null {
  if (typeof window !== 'undefined') {
    const host = window.location.hostname
    if (host === 'localhost' || host === '127.0.0.1') {
      return 'http://localhost:8003/api/voice'
    }
    if (host === PROD_DOMAIN) {
      return 'https://agentapi.summitflow.dev/api/voice'
    }
  }
  return null
}
