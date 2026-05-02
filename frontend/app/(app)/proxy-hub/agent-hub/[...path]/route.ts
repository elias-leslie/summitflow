/**
 * Agent Hub proxy Route Handler.
 *
 * Lives at /proxy-hub/agent-hub/[...path] and is reached via a beforeFiles
 * rewrite: /api/agent-hub/* -> /proxy-hub/agent-hub/* (see next.config.ts).
 * This ensures agent-hub requests are intercepted before the catch-all
 * /api/* -> localhost:8001 rewrite can grab them.
 *
 * Inlines the proxy logic previously provided by @agent-hub/proxy/next
 * (that package was deleted from agent-hub). Handles auth injection and
 * SSE streaming for proxied requests.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

import { PORTS } from '@/lib/api-config'
import {
  createProxyRouteExports,
  createProxyRouteHandler,
} from '@/lib/proxy-route'

const ENV_PREFIX = 'SUMMITFLOW'

interface ProxyConfig {
  agentHubUrl: string
  clientId: string
  requestSource: string
}

function resolveConfig(): ProxyConfig {
  const envKey = (key: string) => `${ENV_PREFIX}_${key}`
  return {
    agentHubUrl:
      process.env.AGENT_HUB_URL ?? `http://localhost:${PORTS.agentHub}`,
    clientId: process.env[envKey('CLIENT_ID')] ?? '',
    requestSource: process.env[envKey('REQUEST_SOURCE')] ?? '',
  }
}

function buildAuthHeaders(config: ProxyConfig): Record<string, string> {
  const headers: Record<string, string> = {}
  if (config.requestSource) headers['X-Request-Source'] = config.requestSource
  if (config.clientId) headers['X-Client-Id'] = config.clientId
  return headers
}

function buildUpstreamUrl(
  config: ProxyConfig,
  path: string[],
  searchParams?: string,
): string {
  const joined = path.join('/')
  const qs = searchParams ? `?${searchParams}` : ''
  return `${config.agentHubUrl}/api/${joined}${qs}`
}

const config = resolveConfig()

function buildForwardHeaders(
  _request: Request,
  config: ProxyConfig,
  bodyPresent: boolean,
): HeadersInit {
  const auth = buildAuthHeaders(config)
  return bodyPresent ? { 'Content-Type': 'application/json', ...auth } : auth
}

const proxyRequest = createProxyRouteHandler<ProxyConfig>({
  resolveConfig: () => config,
  buildUpstreamUrl,
  buildHeaders: buildForwardHeaders,
  bodyMode: 'text',
  queryMode: 'get-delete',
})

export const { GET, POST, PUT, PATCH, DELETE } =
  createProxyRouteExports(proxyRequest)
