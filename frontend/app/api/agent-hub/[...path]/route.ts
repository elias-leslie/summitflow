/**
 * Agent Hub proxy Route Handler.
 *
 * Proxies /api/agent-hub/* requests directly to Agent Hub (localhost:8003)
 * with client credentials injected server-side. This is equivalent to
 * Monkey Fight's Express proxy pattern — single layer, no double-proxying.
 *
 * Route Handlers take priority over Next.js rewrites, so this intercepts
 * before the /api/* -> localhost:8001 rewrite can fire.
 *
 * Supports SSE streaming for /api/complete by piping the response body.
 */

const AGENT_HUB_URL = process.env.AGENT_HUB_URL || 'http://localhost:8003'
const CLIENT_ID = process.env.SUMMITFLOW_CLIENT_ID || ''
const CLIENT_SECRET = process.env.SUMMITFLOW_CLIENT_SECRET || ''
const REQUEST_SOURCE = process.env.SUMMITFLOW_REQUEST_SOURCE || 'summitflow-frontend'

function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {
    'X-Request-Source': REQUEST_SOURCE,
  }
  if (CLIENT_ID) headers['X-Client-Id'] = CLIENT_ID
  if (CLIENT_SECRET) headers['X-Client-Secret'] = CLIENT_SECRET
  return headers
}

function buildUpstreamUrl(path: string[], searchParams: string): string {
  const joined = path.join('/')
  const qs = searchParams ? `?${searchParams}` : ''
  return `${AGENT_HUB_URL}/api/${joined}${qs}`
}

export async function GET(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params
  const url = buildUpstreamUrl(path, new URL(request.url).searchParams.toString())

  const response = await fetch(url, {
    headers: authHeaders(),
  })

  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('Content-Type') || 'application/json',
    },
  })
}

export async function POST(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params
  const url = buildUpstreamUrl(path, '')
  const body = await request.text()

  const response = await fetch(url, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body,
  })

  const contentType = response.headers.get('Content-Type') || 'application/json'
  const isSSE = contentType.includes('text/event-stream')

  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': contentType,
      ...(isSSE
        ? {
            'Cache-Control': 'no-cache, no-transform',
            'X-Accel-Buffering': 'no',
            Connection: 'keep-alive',
          }
        : {}),
    },
  })
}

export async function PUT(
  request: Request,
  { params }: { params: Promise<{ path: string[] }> },
): Promise<Response> {
  const { path } = await params
  const url = buildUpstreamUrl(path, '')
  const body = await request.text()

  const response = await fetch(url, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
      ...authHeaders(),
    },
    body,
  })

  return new Response(response.body, {
    status: response.status,
    headers: {
      'Content-Type': response.headers.get('Content-Type') || 'application/json',
    },
  })
}
