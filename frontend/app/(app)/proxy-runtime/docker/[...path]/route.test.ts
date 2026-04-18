import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { GET, POST } from './route'

const fetchMock = vi.fn()
const originalApiUrl = process.env.API_URL
const originalInternalSecret = process.env.INTERNAL_SERVICE_SECRET

vi.stubGlobal('fetch', fetchMock)

describe('runtime docker proxy route', () => {
  beforeEach(() => {
    fetchMock.mockReset()
    process.env.API_URL = 'http://localhost:8001'
    process.env.INTERNAL_SERVICE_SECRET = 'test-secret'
  })

  afterEach(() => {
    if (originalApiUrl === undefined) {
      delete process.env.API_URL
    } else {
      process.env.API_URL = originalApiUrl
    }
    if (originalInternalSecret === undefined) {
      delete process.env.INTERNAL_SERVICE_SECRET
    } else {
      process.env.INTERNAL_SERVICE_SECRET = originalInternalSecret
    }
  })

  it('injects the internal secret for log streaming requests and preserves sse headers', async () => {
    const body = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode('data: hello\n\n'))
        controller.close()
      },
    })
    fetchMock.mockResolvedValueOnce(
      new Response(body, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
      }),
    )

    const response = await GET(
      new Request(
        'http://localhost/proxy-runtime/docker/logs/monkey-fight?follow=true&tail=50',
        {
          headers: { Accept: 'text/event-stream' },
        },
      ),
      { params: Promise.resolve({ path: ['logs', 'monkey-fight'] }) },
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    const headers = new Headers(init?.headers)

    expect(url).toBe(
      'http://localhost:8001/api/docker/logs/monkey-fight?follow=true&tail=50',
    )
    expect(headers.get('x-internal-secret')).toBe('test-secret')
    expect(headers.get('accept')).toBe('text/event-stream')
    expect(response.status).toBe(200)
    expect(response.headers.get('Content-Type')).toContain('text/event-stream')
    expect(response.headers.get('Cache-Control')).toContain('no-cache')
  })

  it('injects the internal secret for runtime service actions', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(
        JSON.stringify({ success: true, message: 'Stopped monkey-fight' }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )

    const response = await POST(
      new Request('http://localhost/proxy-runtime/docker/stop/monkey-fight', {
        method: 'POST',
      }),
      { params: Promise.resolve({ path: ['stop', 'monkey-fight'] }) },
    )

    expect(fetchMock).toHaveBeenCalledTimes(1)
    const [url, init] = fetchMock.mock.calls[0] ?? []
    const headers = new Headers(init?.headers)

    expect(url).toBe('http://localhost:8001/api/docker/stop/monkey-fight')
    expect(init?.method).toBe('POST')
    expect(headers.get('x-internal-secret')).toBe('test-secret')
    await expect(response.json()).resolves.toEqual({
      success: true,
      message: 'Stopped monkey-fight',
    })
  })
})
