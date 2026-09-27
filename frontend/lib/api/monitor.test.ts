import { afterEach, describe, expect, it, vi } from 'vitest'
import { monitorApi } from './monitor'

afterEach(() => vi.unstubAllGlobals())

describe('monitorApi.logServices', () => {
  it('collects every service page and preserves source errors', async () => {
    const first = Array.from({ length: 100 }, (_, index) => ({
      value: { service: `unit-${index}.service`, scope: 'system' },
    }))
    const pages = [
      {
        schema: 1,
        generated_at: '2026-09-27T12:00:00Z',
        requested: {},
        coverage: { availability: 'partial', units_seen: 101 },
        items: first,
        next_cursor: 'page-two',
        truncated: true,
        errors: [{ code: 'source_truncated' }],
      },
      {
        schema: 1,
        generated_at: '2026-09-27T12:00:01Z',
        requested: {},
        coverage: { availability: 'ok', units_seen: 101 },
        items: [{ value: { service: 'unit-100.service', scope: 'system' } }],
        next_cursor: null,
        truncated: false,
        errors: [],
      },
    ]
    const fetcher = vi.fn().mockImplementation(
      async () =>
        new Response(JSON.stringify(pages.shift()), {
          headers: { 'Content-Type': 'application/json' },
        }),
    )
    vi.stubGlobal('fetch', fetcher)

    const result = await monitorApi.logServices('system')
    expect(result.items).toHaveLength(101)
    expect(result.items.at(-1)?.value).toEqual({
      service: 'unit-100.service',
      scope: 'system',
    })
    expect(result.next_cursor).toBeNull()
    expect(result.truncated).toBe(false)
    expect(result.coverage.availability).toBe('partial')
    expect(result.errors).toEqual([{ code: 'source_truncated' }])
    expect(fetcher).toHaveBeenCalledTimes(2)
    expect(fetcher.mock.calls[1][0]).toContain('cursor=page-two')
  })
})
