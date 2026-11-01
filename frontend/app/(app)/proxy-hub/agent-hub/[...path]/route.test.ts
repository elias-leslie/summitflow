import { mkdtempSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GET, POST } from './route'

const fetchMock = vi.fn()
const originalApiUrl = process.env.API_URL
const originalOwnerTokenFile = process.env.AGENT_HUB_OWNER_TOKEN_FILE

vi.stubGlobal('fetch', fetchMock)

function meResponse(isOwner: boolean): Response {
  return new Response(
    JSON.stringify({
      authenticated: true,
      is_owner: isOwner,
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
    if (originalOwnerTokenFile === undefined) {
      delete process.env.AGENT_HUB_OWNER_TOKEN_FILE
    } else {
      process.env.AGENT_HUB_OWNER_TOKEN_FILE = originalOwnerTokenFile
    }
  })

  async function ownerWrite(headers: Record<string, string> = {}) {
    fetchMock
      .mockResolvedValueOnce(meResponse(true))
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))
    const response = await POST(
      new Request('http://localhost/proxy-hub/agent-hub/memory', {
        method: 'POST',
        headers: { ...identityHeaders, ...headers },
        body: '{"content":"x"}',
      }),
      { params: Promise.resolve({ path: ['memory'] }) },
    )
    expect(response.status).toBe(200)
    const [, init] = fetchMock.mock.calls.at(-1) ?? []
    return new Headers(init?.headers)
  }

  it('marks owner writes with the Agent Hub owner token so they are not queued for review', async () => {
    const dir = mkdtempSync(join(tmpdir(), 'agent-hub-owner-'))
    try {
      process.env.AGENT_HUB_OWNER_TOKEN_FILE = join(dir, 'token')
      writeFileSync(process.env.AGENT_HUB_OWNER_TOKEN_FILE, 'owner-secret\n')

      const owner = await ownerWrite()
      expect(owner.get('x-agent-hub-owner-token')).toBe('owner-secret')

      const agent = await ownerWrite({
        'X-Context-Writer': 'delivery=abc; session=aico-widget-1',
      })
      expect(agent.get('x-agent-hub-owner-token')).toBeNull()
      expect(agent.get('x-context-writer')).toBe(
        'delivery=abc; session=aico-widget-1',
      )
    } finally {
      rmSync(dir, { recursive: true, force: true })
    }
  })

  it('sends no owner token when the token file is missing', async () => {
    process.env.AGENT_HUB_OWNER_TOKEN_FILE =
      '/nonexistent/agent-hub-owner-token'
    const headers = await ownerWrite()
    expect(headers.get('x-agent-hub-owner-token')).toBeNull()
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

  it('refuses a cross-site agent write before asking who the caller is', async () => {
    const response = await POST(
      new Request('http://localhost:3001/proxy-hub/agent-hub/agents', {
        method: 'POST',
        headers: {
          ...identityHeaders,
          host: 'localhost:3001',
          origin: 'https://evil.example',
          'content-type': 'text/plain',
        },
        body: '{"name":"x"}',
      }),
      { params: Promise.resolve({ path: ['agents'] }) },
    )

    expect(response.status).toBe(403)
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('does not forward the browser Origin to Agent Hub', async () => {
    fetchMock
      .mockResolvedValueOnce(meResponse(true))
      .mockResolvedValueOnce(new Response('{}', { status: 200 }))

    const response = await POST(
      new Request('http://localhost:3001/proxy-hub/agent-hub/agents', {
        method: 'POST',
        headers: {
          ...identityHeaders,
          host: 'localhost:3001',
          origin: 'http://localhost:3001',
          'sec-fetch-site': 'same-origin',
        },
        body: '{"name":"x"}',
      }),
      { params: Promise.resolve({ path: ['agents'] }) },
    )

    expect(response.status).toBe(200)
    const [, init] = fetchMock.mock.calls[1] ?? []
    const headers = new Headers(init?.headers)
    expect(headers.get('origin')).toBeNull()
    expect(headers.get('sec-fetch-site')).toBeNull()
  })
})
