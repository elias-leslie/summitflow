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

// ---------------------------------------------------------------------------
// Headers
// ---------------------------------------------------------------------------

const SSE_HEADERS: Record<string, string> = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
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

// ---------------------------------------------------------------------------
// Route Handlers
// ---------------------------------------------------------------------------

type RouteContext = { params: Promise<{ path: string[] }> }

const config = resolveConfig()
const auth = buildAuthHeaders(config)

function proxyResponse(response: Response): Response {
  const contentType = response.headers.get('Content-Type') ?? 'application/json'
  const isSSE = contentType.includes('text/event-stream')
  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': contentType,
      ...(isSSE ? SSE_HEADERS : {}),
    },
  })
}

async function proxyWithBody(
  request: Request,
  { params }: RouteContext,
  method: string,
): Promise<Response> {
  const { path } = await params
  const qs =
    method === 'DELETE'
      ? new URL(request.url).searchParams.toString()
      : undefined
  const url = buildUpstreamUrl(config, path, qs)
  const body = await request.text()
  const response = await fetch(url, {
    method,
    headers: body ? { 'Content-Type': 'application/json', ...auth } : auth,
    ...(body ? { body } : {}),
  })
  return proxyResponse(response)
}

export async function GET(request: Request, { params }: RouteContext) {
  const { path } = await params
  const url = buildUpstreamUrl(
    config,
    path,
    new URL(request.url).searchParams.toString(),
  )
  const response = await fetch(url, { headers: auth })
  return proxyResponse(response)
}

export async function POST(request: Request, context: RouteContext) {
  return proxyWithBody(request, context, 'POST')
}

export async function PUT(request: Request, context: RouteContext) {
  return proxyWithBody(request, context, 'PUT')
}

export async function PATCH(request: Request, context: RouteContext) {
  return proxyWithBody(request, context, 'PATCH')
}

export async function DELETE(request: Request, context: RouteContext) {
  return proxyWithBody(request, context, 'DELETE')
}
