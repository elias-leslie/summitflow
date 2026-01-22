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

  // Production: dev.summitflow.dev -> devapi.summitflow.dev
  if (host === PROD_DOMAIN) {
    return `https://${PROD_API_DOMAIN}`
  }

  // Fallback: use localhost (shouldn't happen in normal use)
  return `http://localhost:${PORTS.backend}`
}

/**
 * Get WebSocket URL for a given path.
 *
 * Automatically handles ws/wss based on current protocol.
 *
 * IMPORTANT: In production, WebSocket uses same-origin routing via Cloudflare Tunnel
 * path-based rules. This avoids CF Access cookie issues (cookies are subdomain-specific).
 * The Tunnel config routes /ws/* paths directly to the backend.
 *
 * @param path - WebSocket path (e.g., /ws/execution/task-123)
 * @returns Full WebSocket URL
 */
export function getWsUrl(path: string): string {
  if (typeof window === 'undefined') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  const host = window.location.hostname

  // Development
  if (host === 'localhost' || host === '127.0.0.1') {
    return `ws://localhost:${PORTS.backend}${path}`
  }

  // Production: use same-origin WebSocket via Cloudflare Tunnel path routing
  // Tunnel config routes /ws/* paths directly to backend, avoiding CF Access cookie issues
  if (host === PROD_DOMAIN) {
    return `${protocol}//${PROD_DOMAIN}${path}`
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
