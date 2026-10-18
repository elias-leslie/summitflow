import { PORTS } from '@/lib/api-config'

const SSE_HEADERS: Record<string, string> = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
}

export type ProxyRouteContext = { params: Promise<{ path: string[] }> }

type BodyMode = 'arrayBuffer' | 'text'
type QueryMode = 'all' | 'get-delete'

/** Base URL of the SummitFlow backend as seen from the Next.js server. */
export function backendApiUrl(): string {
  return process.env.API_URL ?? `http://localhost:${PORTS.backend}`
}

/**
 * Copy the caller's identity onto an upstream request.
 *
 * This proxy reaches the backend over loopback, so it forwards only what the
 * caller itself sent (Access JWT, cookie, owner token, original host) and adds no
 * credential of its own: the proxy's own user never counts as the caller.
 */
export function setIdentityHeaders(
  request: Request,
  headers: Headers,
): Headers {
  const jwt = request.headers.get('cf-access-jwt-assertion')
  const cookie = request.headers.get('cookie')
  const host =
    request.headers.get('x-forwarded-host') ?? request.headers.get('host')
  if (jwt) headers.set('Cf-Access-Jwt-Assertion', jwt)
  if (cookie) headers.set('Cookie', cookie)
  const ownerToken = request.headers.get('x-summitflow-owner-token')
  if (ownerToken) headers.set('X-SummitFlow-Owner-Token', ownerToken)
  if (host) headers.set('X-Forwarded-Host', host)
  return headers
}

/**
 * Resolve the caller through the backend and reject anyone who is not an owner.
 * Returns null when the caller is an owner, else the error response to send.
 */
export async function requireOwner(request: Request): Promise<Response | null> {
  try {
    const response = await fetch(`${backendApiUrl()}/api/auth/me`, {
      headers: setIdentityHeaders(
        request,
        new Headers({ Accept: 'application/json' }),
      ),
      cache: 'no-store',
    })
    if (response.ok) {
      const me = (await response.json()) as { is_owner?: unknown }
      if (me.is_owner === true) return null
    }
  } catch {
    return Response.json(
      { detail: 'Could not verify SummitFlow identity' },
      { status: 503 },
    )
  }
  return Response.json({ detail: 'Owner access required' }, { status: 403 })
}

const UNSAFE_METHODS = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
const OTHER_SITE_FETCH = new Set(['cross-site', 'same-site'])

function originAuthority(origin: string): string | null {
  try {
    const url = new URL(origin)
    return url.protocol === 'http:' || url.protocol === 'https:'
      ? `${url.protocol}//${url.host}`
      : null
  } catch {
    return null
  }
}

function hostAuthority(host: string | null, protocol: string): string | null {
  const first = host?.split(',')[0]?.trim()
  return first ? originAuthority(`${protocol}//${first}`) : null
}

/**
 * Refuse a browser write that another site's page sent.
 *
 * The proxies act for the caller with server-side credentials (the internal
 * secret, SummitFlow's Agent Hub client id), and loopback callers count as the
 * owner, so a page the owner happens to open could otherwise POST here.
 * POST/PUT/PATCH/DELETE carrying Origin or Sec-Fetch-Site must come from this
 * origin; callers that send neither (st, agents, curl) pass.
 */
export function crossSiteRefusal(
  request: Request,
  method: string,
): Response | null {
  if (!UNSAFE_METHODS.has(method)) return null
  const site = request.headers.get('sec-fetch-site')?.trim().toLowerCase()
  const origin = request.headers.get('origin')
  if (site && OTHER_SITE_FETCH.has(site)) return sameOriginRequired()
  if (site === 'same-origin' || (!site && origin === null)) return null
  const authority = origin === null ? null : originAuthority(origin)
  if (!authority) return sameOriginRequired()
  const protocol = new URL(authority).protocol
  const ours = [
    request.headers.get('host'),
    request.headers.get('x-forwarded-host'),
  ].map((host) => hostAuthority(host, protocol))
  return ours.includes(authority) ? null : sameOriginRequired()
}

function sameOriginRequired(): Response {
  return Response.json(
    { detail: 'Same-origin request required' },
    { status: 403 },
  )
}

type ProxyRouteOptions<Config> = {
  resolveConfig: () => Config
  buildUpstreamUrl: (
    config: Config,
    path: string[],
    searchParams?: string,
  ) => string
  buildHeaders: (
    request: Request,
    config: Config,
    bodyPresent: boolean,
  ) => HeadersInit
  bodyMode?: BodyMode
  queryMode?: QueryMode
  onTransportError?: (error: unknown) => Response
  /** Runs before proxying; a returned Response is sent instead of the upstream call. */
  authorize?: (request: Request) => Promise<Response | null>
}

export function proxyResponse(response: Response): Response {
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

async function readForwardBody(
  request: Request,
  method: string,
  mode: BodyMode,
): Promise<BodyInit | undefined> {
  if (method === 'GET' || method === 'HEAD') return undefined

  if (mode === 'text') {
    const body = await request.text()
    return body || undefined
  }

  const body = await request.clone().arrayBuffer()
  return body.byteLength > 0 ? body : undefined
}

function shouldForwardQuery(method: string, mode: QueryMode): boolean {
  if (mode === 'all') return true
  return method === 'GET' || method === 'DELETE'
}

export function createProxyRouteHandler<Config>({
  resolveConfig,
  buildUpstreamUrl,
  buildHeaders,
  bodyMode = 'arrayBuffer',
  queryMode = 'all',
  onTransportError,
  authorize,
}: ProxyRouteOptions<Config>) {
  return async function proxyRouteRequest(
    request: Request,
    { params }: ProxyRouteContext,
    method: string,
  ): Promise<Response> {
    const crossSite = crossSiteRefusal(request, method)
    if (crossSite) return crossSite
    if (authorize) {
      const denied = await authorize(request)
      if (denied) return denied
    }
    const { path } = await params
    const config = resolveConfig()
    const searchParams = shouldForwardQuery(method, queryMode)
      ? new URL(request.url).searchParams.toString()
      : undefined
    const url = buildUpstreamUrl(config, path, searchParams)
    const body = await readForwardBody(request, method, bodyMode)

    try {
      const response = await fetch(url, {
        method,
        headers: buildHeaders(request, config, body !== undefined),
        ...(body !== undefined ? { body } : {}),
      })
      return proxyResponse(response)
    } catch (error) {
      if (onTransportError) return onTransportError(error)
      throw error
    }
  }
}

type ProxyRequestHandler = (
  request: Request,
  context: ProxyRouteContext,
  method: string,
) => Promise<Response>

export function createProxyRouteExports(proxyRequest: ProxyRequestHandler) {
  return {
    GET: (request: Request, context: ProxyRouteContext) =>
      proxyRequest(request, context, 'GET'),
    POST: (request: Request, context: ProxyRouteContext) =>
      proxyRequest(request, context, 'POST'),
    PUT: (request: Request, context: ProxyRouteContext) =>
      proxyRequest(request, context, 'PUT'),
    PATCH: (request: Request, context: ProxyRouteContext) =>
      proxyRequest(request, context, 'PATCH'),
    DELETE: (request: Request, context: ProxyRouteContext) =>
      proxyRequest(request, context, 'DELETE'),
  }
}
