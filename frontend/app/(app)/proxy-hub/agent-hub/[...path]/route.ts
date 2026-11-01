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
 * SSE streaming for proxied requests. Upstream calls carry SummitFlow's own
 * client identity, so only SummitFlow owners may use this proxy.
 *
 * Writes through here are the owner's (requireOwner ran first), so they carry
 * Agent Hub's owner token (AGENT_HUB_OWNER_TOKEN_FILE): Agent Hub records them
 * as owner edits, which its context review queue never asks the owner to
 * review. A caller that names an agent session (X-Context-Writer) is passed
 * through as that agent instead, so its writes still queue.
 */

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------

import { readFileSync } from 'node:fs'
import { PORTS } from '@/lib/api-config'
import {
  createProxyRouteExports,
  createProxyRouteHandler,
  requireOwner,
} from '@/lib/proxy-route'

const ENV_PREFIX = 'SUMMITFLOW'
const CONTEXT_WRITER_HEADER = 'X-Context-Writer'
const OWNER_TOKEN_HEADER = 'X-Agent-Hub-Owner-Token'

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

/** Agent Hub's owner token, read per request so a rotated file applies; absent when unreadable. */
function agentHubOwnerToken(): string | null {
  const path = process.env.AGENT_HUB_OWNER_TOKEN_FILE?.trim()
  if (!path) return null
  try {
    return readFileSync(path, 'utf8').trim() || null
  } catch {
    return null
  }
}

/** Who Agent Hub should record as the writer: the named agent session, else the owner. */
function writerHeaders(request: Request): Record<string, string> {
  const agent = request.headers.get(CONTEXT_WRITER_HEADER)?.trim()
  if (agent) return { [CONTEXT_WRITER_HEADER]: agent }
  const token = agentHubOwnerToken()
  return token ? { [OWNER_TOKEN_HEADER]: token } : {}
}

function buildForwardHeaders(
  request: Request,
  config: ProxyConfig,
  bodyPresent: boolean,
): HeadersInit {
  const auth = { ...buildAuthHeaders(config), ...writerHeaders(request) }
  return bodyPresent ? { 'Content-Type': 'application/json', ...auth } : auth
}

const proxyRequest = createProxyRouteHandler<ProxyConfig>({
  resolveConfig: () => config,
  buildUpstreamUrl,
  buildHeaders: buildForwardHeaders,
  bodyMode: 'text',
  queryMode: 'get-delete',
  authorize: requireOwner,
})

export const { GET, POST, PUT, PATCH, DELETE } =
  createProxyRouteExports(proxyRequest)
