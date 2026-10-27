import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildPageUrl, fetchProjectPages, type ProjectPage } from './projects'

function respond(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

const page = (overrides: Partial<ProjectPage> = {}): ProjectPage => ({
  path: '/settings',
  name: 'Settings',
  url: null,
  port: null,
  ...overrides,
})

describe('fetchProjectPages', () => {
  afterEach(() => vi.restoreAllMocks())

  it('reads the live pages list for the project', async () => {
    const items = [page(), page({ path: '/', name: 'Home', port: 3001 })]
    const fetch = respond({ items })

    expect(await fetchProjectPages('summitflow')).toEqual(items)
    expect(fetch.mock.calls[0][0]).toBe('/api/projects/summitflow/pages')
  })

  it('surfaces API failures', async () => {
    respond({ message: 'Page discovery failed' }, 503)
    await expect(fetchProjectPages('summitflow')).rejects.toThrow(
      'Page discovery failed',
    )
  })
})

describe('buildPageUrl', () => {
  it('prefers an explicit url', () => {
    expect(
      buildPageUrl(
        page({ url: 'https://app.example.test/settings', port: 3001 }),
      ),
    ).toBe('https://app.example.test/settings')
  })

  it('falls back to localhost with the port when url is empty', () => {
    expect(buildPageUrl(page({ url: '', port: 3001 }))).toBe(
      'http://localhost:3001/settings',
    )
    expect(buildPageUrl(page({ port: 3001 }))).toBe(
      'http://localhost:3001/settings',
    )
  })

  it('falls back to the bare path without url or port', () => {
    expect(buildPageUrl(page())).toBe('/settings')
  })
})
