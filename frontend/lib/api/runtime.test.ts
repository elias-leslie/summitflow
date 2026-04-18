import { afterEach, describe, expect, it, vi } from 'vitest'
import { runtimeApi } from './runtime'

describe('runtimeApi', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('uses same-origin proxy paths for runtime log requests', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ logs: 'line one' }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    vi.stubGlobal('fetch', fetchMock)

    await runtimeApi.getLogs('monkey-fight', 200)

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe(
      '/api/docker/logs/monkey-fight?tail=200',
    )
  })

  it('uses same-origin proxy paths for runtime service actions and log streaming', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ success: true, message: 'Stopped monkey-fight' }),
        {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        },
      ),
    )
    vi.stubGlobal('fetch', fetchMock)

    await runtimeApi.stop('monkey-fight')

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(fetchMock.mock.calls[0]?.[0]).toBe('/api/docker/stop/monkey-fight')
    expect(runtimeApi.logStreamUrl('monkey-fight', 50)).toBe(
      '/api/docker/logs/monkey-fight?follow=true&tail=50',
    )
  })
})
