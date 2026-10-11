import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GET, POST } from './route'

const fetchMock = vi.fn()
const originalApiUrl = process.env.API_URL

vi.stubGlobal('fetch', fetchMock)

function meResponse(isOwner: boolean): Response {
  return new Response(
    JSON.stringify({
      authenticated: true,
      is_owner: isOwner,
      is_viewer: !isOwner,
    }),
    { status: 200, headers: { 'Content-Type': 'application/json' } },
  )
}

const identityHeaders = {
  'Cf-Access-Jwt-Assertion': 'caller-jwt',
  Cookie: 'CF_Authorization=caller-cookie',
}

describe('agent hub proxy route', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    process.env.API_URL = 'http://localhost:8001'
  })

  afterEach(() => {
    if (originalApiUrl === undefined) {
      delete process.env.API_URL
    } else {
      process.env.API_URL = originalApiUrl
    }
  })

  it('rejects non-owners before calling Agent Hub', async () => {
    fetchMock.mockResolvedValueOnce(meResponse(false))

    const response = await POST(
      new Request('http://localhost/proxy-hub/agent-hub/sessions', {
        method: 'POST',
        headers: { ...identityHeaders, 'Content-Type': 'application/json' },
        body: JSON.stringify({ prompt: 'hi' }),
      }),
      { params: Promise.resolve({ path: ['sessions'] }) },
    )

    expect(response.status).toBe(403)
    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    const headers = new Headers(init?.headers)
    expect(url).toBe('http://localhost:8001/api/auth/me')
    expect(headers.get('cf-access-jwt-assertion')).toBe('caller-jwt')
    expect(headers.get('cookie')).toBe('CF_Authorization=caller-cookie')
  })

  it('rejects callers the backend cannot authenticate', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ detail: 'Invalid Cloudflare Access token' }),
        {
          status: 401,
        },
      ),
    )

    const response = await GET(
      new Request('http://localhost/proxy-hub/agent-hub/sessions', {
        headers: identityHeaders,
      }),
      { params: Promise.resolve({ path: ['sessions'] }) },
    )

    expect(response.status).toBe(403)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('fails closed when identity cannot be verified', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('connect ECONNREFUSED'))

    const response = await GET(
      new Request('http://localhost/proxy-hub/agent-hub/sessions'),
      { params: Promise.resolve({ path: ['sessions'] }) },
    )

    expect(response.status).toBe(503)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('proxies owners to Agent Hub', async () => {
    fetchMock.mockResolvedValueOnce(meResponse(true)).mockResolvedValueOnce(
      new Response(JSON.stringify({ sessions: [] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const response = await GET(
      new Request('http://localhost/proxy-hub/agent-hub/sessions?limit=5', {
        headers: identityHeaders,
      }),
      { params: Promise.resolve({ path: ['sessions'] }) },
    )

    expect(response.status).toBe(200)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    const [url] = fetchMock.mock.calls[1] ?? []
    expect(url).toMatch(/\/api\/sessions\?limit=5$/)
    await expect(response.json()).resolves.toEqual({ sessions: [] })
  })
})
