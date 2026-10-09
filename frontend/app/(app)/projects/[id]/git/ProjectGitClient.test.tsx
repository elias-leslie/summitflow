import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { development, repo } from '@/components/git/developmentFixtures'
import { ProjectGitClient } from './ProjectGitClient'

const api = vi.hoisted(() => ({
  fetchProjectGitStatus: vi.fn(),
  fetchProjectDevelopmentStatus: vi.fn(),
}))
vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'project-alpha' }),
}))
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
      <ProjectGitClient />
    </QueryClientProvider>,
  )
}
beforeEach(() => vi.clearAllMocks())
describe('Project Development', () => {
  it('uses the route project for both evidence sources', async () => {
    api.fetchProjectGitStatus.mockResolvedValue({
      repositories: [repo],
      total: 1,
    })
    api.fetchProjectDevelopmentStatus.mockResolvedValue(development)
    renderClient()
    expect(await screen.findByText('alpha development')).toBeInTheDocument()
    expect(api.fetchProjectDevelopmentStatus).toHaveBeenCalledWith(
      'project-alpha',
    )
    expect(api.fetchProjectGitStatus).toHaveBeenCalledWith('project-alpha')
  })
  it('preserves a failed source as an error', async () => {
    api.fetchProjectGitStatus.mockResolvedValue({ repositories: [repo] })
    api.fetchProjectDevelopmentStatus.mockRejectedValue(new Error('store down'))
    renderClient()
    expect(
      await screen.findByText('Could not load development evidence.'),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('No repository found for this project'),
    ).not.toBeInTheDocument()
  })
})
