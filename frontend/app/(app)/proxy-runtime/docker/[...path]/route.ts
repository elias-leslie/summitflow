/**
 * Runtime API proxy Route Handler.
 *
 * Lives at /proxy-runtime/docker/[...path] and is reached via a beforeFiles
 * rewrite: /api/docker/* -> /proxy-runtime/docker/* (see next.config.ts).
 * This allows the first-party runtime UI to call protected backend routes
 * without exposing INTERNAL_SERVICE_SECRET to the browser, and it preserves
 * SSE streaming for live logs.
 */

import { PORTS } from '@/lib/api-config'
import {
  createProxyRouteExports,
  createProxyRouteHandler,
} from '@/lib/proxy-route'

interface RuntimeProxyConfig {
  apiUrl: string
  internalSecret: string
}

function resolveConfig(): RuntimeProxyConfig {
  return {
    apiUrl: process.env.API_URL ?? `http://localhost:${PORTS.backend}`,
    internalSecret: process.env.INTERNAL_SERVICE_SECRET ?? '',
  }
}

function buildUpstreamUrl(
  config: RuntimeProxyConfig,
  path: string[],
  searchParams?: string,
): string {
  const joined = path.map((segment) => encodeURIComponent(segment)).join('/')
  const qs = searchParams ? `?${searchParams}` : ''
  return `${config.apiUrl}/api/docker/${joined}${qs}`
}

function buildForwardHeaders(
  request: Request,
  config: RuntimeProxyConfig,
  bodyPresent: boolean,
): Headers {
  const headers = new Headers()
  const accept = request.headers.get('accept')
  const contentType = request.headers.get('content-type')
  const liveSessionToken = request.headers.get('x-live-session-token')

  if (accept) headers.set('Accept', accept)
  if (bodyPresent && contentType) headers.set('Content-Type', contentType)
  if (liveSessionToken) headers.set('X-Live-Session-Token', liveSessionToken)
  if (config.internalSecret)
    headers.set('X-Internal-Secret', config.internalSecret)
  return headers
}

function proxyTransportErrorResponse(error: unknown): Response {
  const message =
    error instanceof Error ? error.message : 'Upstream proxy transport error'
  return Response.json(
    {
      error: 'Runtime proxy upstream unavailable',
      detail: message,
    },
    { status: 502 },
  )
}

const proxyRequest = createProxyRouteHandler<RuntimeProxyConfig>({
  resolveConfig,
  buildUpstreamUrl,
  buildHeaders: buildForwardHeaders,
  bodyMode: 'arrayBuffer',
  queryMode: 'all',
  onTransportError: proxyTransportErrorResponse,
})

export const { GET, POST, PUT, PATCH, DELETE } =
  createProxyRouteExports(proxyRequest)
