import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { development, repo } from '@/components/git/developmentFixtures'
import { GitClient } from './GitClient'

const api = vi.hoisted(() => ({ fetchDevelopmentStatus: vi.fn() }))
vi.mock('@/lib/api/git', () => api)
vi.mock('@/components/git/ProjectRow', () => ({
  ProjectRow: ({ repo }: { repo: { name: string } }) => (
    <div>{repo.name} development</div>
  ),
}))
function renderClient() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <GitClient />
    </QueryClientProvider>,
  )
}
beforeEach(() => vi.clearAllMocks())
describe('Development route', () => {
  it('loads the shared projection without triggering publication or remote actions', async () => {
    api.fetchDevelopmentStatus.mockResolvedValue({
      version: 'development.v1',
      repositories: [{ repo, development }],
      total: 1,
    })
    renderClient()
    expect(screen.getByText('Development')).toBeInTheDocument()
    expect(await screen.findByText('alpha development')).toBeInTheDocument()
  })
  it('distinguishes a failed request from an empty repository list', async () => {
    api.fetchDevelopmentStatus.mockRejectedValue(new Error('unavailable'))
    renderClient()
    expect(
      await screen.findByText('Could not load development evidence.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No managed repositories found'),
    ).not.toBeInTheDocument()
  })
  it('reports a genuinely empty repository list', async () => {
    api.fetchDevelopmentStatus.mockResolvedValue({
      version: 'development.v1',
      repositories: [],
      total: 0,
    })
    renderClient()
    expect(
      await screen.findByText('No managed repositories found'),
    ).toBeInTheDocument()
  })
  it('keeps unavailable local repositories distinct from an empty inventory', async () => {
    api.fetchDevelopmentStatus.mockResolvedValue({
      version: 'development.v1',
      repositories: [],
      total: 1,
      unavailable_repositories: [
        {
          path: '/repos/alpha',
          name: 'alpha',
          reason: 'Local repository status unavailable',
        },
      ],
    })
    renderClient()
    expect(
      await screen.findByText('alpha: Local repository status unavailable'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No managed repositories found'),
    ).not.toBeInTheDocument()
  })
})
