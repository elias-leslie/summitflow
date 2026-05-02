const SSE_HEADERS: Record<string, string> = {
  'Cache-Control': 'no-cache, no-transform',
  'X-Accel-Buffering': 'no',
  Connection: 'keep-alive',
}

export type ProxyRouteContext = { params: Promise<{ path: string[] }> }

type BodyMode = 'arrayBuffer' | 'text'
type QueryMode = 'all' | 'get-delete'

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
}: ProxyRouteOptions<Config>) {
  return async function proxyRouteRequest(
    request: Request,
    { params }: ProxyRouteContext,
    method: string,
  ): Promise<Response> {
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
