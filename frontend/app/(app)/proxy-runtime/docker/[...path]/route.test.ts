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

  it('forwards request bodies without text re-encoding', async () => {
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ status: 'queued' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )

    const payload = JSON.stringify({ note: 'burst create', keep_local: false })
    await POST(
      new Request(
        'http://localhost/proxy-runtime/docker/backup-sources/test/backups',
        {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: payload,
        },
      ),
      {
        params: Promise.resolve({
          path: ['backup-sources', 'test', 'backups'],
        }),
      },
    )

    const [, init] = fetchMock.mock.calls[0] ?? []
    expect(init?.body).toBeInstanceOf(ArrayBuffer)
    expect(new TextDecoder().decode(init?.body as ArrayBuffer)).toBe(payload)
  })

  it('keeps concurrent queued POST bodies isolated', async () => {
    fetchMock.mockImplementation(async (_url, init) => {
      const body = init?.body as ArrayBuffer | undefined
      return new Response(
        JSON.stringify({
          status: 'queued',
          note: body ? new TextDecoder().decode(body) : null,
        }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      )
    })

    const requests = await Promise.all([
      POST(
        new Request(
          'http://localhost/proxy-runtime/docker/backup-sources/a/backups',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: 'one' }),
          },
        ),
        {
          params: Promise.resolve({ path: ['backup-sources', 'a', 'backups'] }),
        },
      ).then((response) => response.json()),
      POST(
        new Request(
          'http://localhost/proxy-runtime/docker/backup-sources/b/backups',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: 'two' }),
          },
        ),
        {
          params: Promise.resolve({ path: ['backup-sources', 'b', 'backups'] }),
        },
      ).then((response) => response.json()),
      POST(
        new Request(
          'http://localhost/proxy-runtime/docker/backup-sources/c/backups',
          {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ note: 'three' }),
          },
        ),
        {
          params: Promise.resolve({ path: ['backup-sources', 'c', 'backups'] }),
        },
      ).then((response) => response.json()),
    ])

    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(requests).toEqual([
      { status: 'queued', note: '{"note":"one"}' },
      { status: 'queued', note: '{"note":"two"}' },
      { status: 'queued', note: '{"note":"three"}' },
    ])
  })
})
