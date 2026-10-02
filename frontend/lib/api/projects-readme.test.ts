import { afterEach, describe, expect, it, vi } from 'vitest'
import { fetchProjectReadme } from './projects'

function respond(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

describe('fetchProjectReadme', () => {
  afterEach(() => vi.restoreAllMocks())

  it.each([
    { project_id: 'summitflow', status: 'available', content: '' },
    { project_id: 'summitflow', status: 'missing', content: null },
    { project_id: 'summitflow', status: 'unavailable', content: null },
  ])('accepts the README contract for $status', async (body) => {
    const fetch = respond(body)
    expect(await fetchProjectReadme('summitflow')).toEqual(body)
    expect(fetch.mock.calls[0][0]).toContain('/api/projects/summitflow/readme')
  })

  it.each([
    null,
    { project_id: 'wrong-project', status: 'available', content: '# Wrong' },
    { project_id: 'summitflow', status: 'available', content: null },
    { project_id: 'summitflow', status: 'missing', content: '# Wrong' },
    { project_id: 'summitflow', status: 'unknown', content: null },
  ])('rejects invalid payloads instead of treating them as empty', async (body) => {
    respond(body)
    await expect(fetchProjectReadme('summitflow')).rejects.toThrow(
      'Invalid README response',
    )
  })

  it('preserves API read failures for the retry state', async () => {
    respond({ message: 'README request failed' }, 503)
    await expect(fetchProjectReadme('summitflow')).rejects.toThrow(
      'README request failed',
    )
  })
})
