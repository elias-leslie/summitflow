import { getApiBaseUrl } from './api-config'

/**
 * Resolve the Agent Hub API base path.
 *
 * Browser requests must stay same-origin so Next.js can rewrite
 * /api/agent-hub/* through the local proxy route.
 * Server-side uses API_URL env var to reach the SummitFlow API
 * (which proxies to Agent Hub), or falls back to localhost.
 */
export function getAgentHubProxyBase(): string {
  if (typeof window === 'undefined') {
    return `${getApiBaseUrl()}/api/agent-hub`
  }

  return '/api/agent-hub'
}
