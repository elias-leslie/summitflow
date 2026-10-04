import { describe, expect, it, vi } from 'vitest'
import { development } from '@/components/git/developmentFixtures'
import { decodeDevelopmentProjection, publishProjectChanges } from './git'

const fetchMock = vi.hoisted(() => vi.fn())
vi.mock('./utils', () => ({ fetchWithErrorHandling: fetchMock }))
vi.mock('../api-config', () => ({
  getApiBaseUrl: () => 'https://example.test',
}))
describe('Development contracts', () => {
  it('rejects malformed external data and unknown projection versions', () => {
    expect(() =>
      decodeDevelopmentProjection({ ...development, version: 'future' }),
    ).toThrow('Unsupported')
    expect(() =>
      decodeDevelopmentProjection({
        ...development,
        accepted: { ...development.accepted, full_coverage: 'yes' },
      }),
    ).toThrow('malformed')
    expect(
      decodeDevelopmentProjection(development).working_tree.unpublished,
    ).toBe(1)
  })
  it('sends the exact accepted commit in the publication request', async () => {
    fetchMock.mockResolvedValue({ status: 'pending' })
    const sha = 'a'.repeat(40)
    await publishProjectChanges('project-alpha', sha)
    expect(fetchMock).toHaveBeenCalledWith(
      'https://example.test/api/projects/project-alpha/git/publish',
      expect.objectContaining({
        method: 'POST',
        body: JSON.stringify({ source_sha: sha }),
      }),
    )
  })
})
