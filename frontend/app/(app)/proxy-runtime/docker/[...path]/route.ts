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

const SSE_HEADERS: Record<string, string> = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
}

interface RuntimeProxyConfig {
  apiUrl: string
  internalSecret: string
}

type RouteContext = { params: Promise<{ path: string[] }> }

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
  options: { bodyPresent: boolean },
): Headers {
  const headers = new Headers()
  const accept = request.headers.get('accept')
  const contentType = request.headers.get('content-type')
  const { bodyPresent } = options

  if (accept) headers.set('Accept', accept)
  if (bodyPresent && contentType) headers.set('Content-Type', contentType)
  if (config.internalSecret)
    headers.set('X-Internal-Secret', config.internalSecret)
  return headers
}

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

async function readForwardBody(
  request: Request,
  method: string,
): Promise<ArrayBuffer | undefined> {
  if (method === 'GET' || method === 'HEAD') return undefined

  const clone = request.clone()
  const body = await clone.arrayBuffer()
  return body.byteLength > 0 ? body : undefined
}

async function proxyRequest(
  request: Request,
  { params }: RouteContext,
  method: string,
): Promise<Response> {
  const { path } = await params
  const config = resolveConfig()
  const url = buildUpstreamUrl(
    config,
    path,
    new URL(request.url).searchParams.toString(),
  )
  const body = await readForwardBody(request, method)

  try {
    const response = await fetch(url, {
      method,
      headers: buildForwardHeaders(request, config, {
        bodyPresent: body !== undefined,
      }),
      ...(body ? { body } : {}),
    })
    return proxyResponse(response)
  } catch (error) {
    return proxyTransportErrorResponse(error)
  }
}

export async function GET(request: Request, context: RouteContext) {
  return proxyRequest(request, context, 'GET')
}

export async function POST(request: Request, context: RouteContext) {
  return proxyRequest(request, context, 'POST')
}

export async function PUT(request: Request, context: RouteContext) {
  return proxyRequest(request, context, 'PUT')
}

export async function PATCH(request: Request, context: RouteContext) {
  return proxyRequest(request, context, 'PATCH')
}

export async function DELETE(request: Request, context: RouteContext) {
  return proxyRequest(request, context, 'DELETE')
}
