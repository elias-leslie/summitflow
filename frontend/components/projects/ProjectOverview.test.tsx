import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Project } from '@/lib/api'
import { ProjectOverview } from './ProjectOverview'

const apiMocks = vi.hoisted(() => ({
  fetchProjectReadme: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  fetchProjectReadme: apiMocks.fetchProjectReadme,
}))

vi.mock('../dashboard/ActivityFeed', () => ({
  ActivityFeed: ({ projectId }: { projectId?: string }) => (
    <div data-testid="activity-feed">Activity feed for {projectId}</div>
  ),
}))

function renderOverview(projectOverrides: Partial<Project> = {}) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  const project: Project = {
    id: 'summitflow',
    name: 'SummitFlow',
    base_url: 'http://localhost:3001',
    public_url: 'https://public.example.test',
    health_endpoint: '/health',
    category: 'production',
    sidebar_rank: 1,
    created_at: '2026-04-01T00:00:00Z',
    health_status: 'healthy',
    root_path: '/srv/workspaces/projects/summitflow',
    ...projectOverrides,
  }

  return render(
    <QueryClientProvider client={client}>
      <ProjectOverview project={project} />
    </QueryClientProvider>,
  )
}

describe('ProjectOverview', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.fetchProjectReadme.mockResolvedValue({
      project_id: 'summitflow',
      status: 'available',
      content: '# SummitFlow\n\nProject delivery tools.',
    })
  })

  it('renders the project README and retains recent activity', async () => {
    renderOverview()
    expect(
      await screen.findByRole('heading', { name: 'SummitFlow' }),
    ).toBeInTheDocument()
    expect(screen.getByText('Project delivery tools.')).toBeInTheDocument()
    expect(screen.getByText('Recent Activity')).toBeInTheDocument()
    expect(screen.getByTestId('activity-feed')).toHaveTextContent(
      'Activity feed for summitflow',
    )
    expect(screen.queryByText('Service Status')).not.toBeInTheDocument()
  })

  it('shows README loading independently of recent activity', () => {
    apiMocks.fetchProjectReadme.mockReturnValue(new Promise(() => {}))
    renderOverview()
    expect(screen.getByRole('status')).toHaveTextContent('Loading README.md')
    expect(screen.getByTestId('activity-feed')).toBeInTheDocument()
  })

  it.each([
    ['missing', null, 'No README.md in the project root.'],
    ['unavailable', null, 'README.md is unavailable.'],
    ['available', '   ', 'README.md is empty.'],
  ])('distinguishes the %s README state', async (status, content, message) => {
    apiMocks.fetchProjectReadme.mockResolvedValue({
      project_id: 'summitflow',
      status,
      content,
    })
    renderOverview()
    expect(await screen.findByText(message)).toBeInTheDocument()
  })

  it('retries failed requests and renders the recovered README', async () => {
    apiMocks.fetchProjectReadme.mockRejectedValueOnce(
      new Error('README read failed'),
    )
    renderOverview()
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'README read failed',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(
      await screen.findByRole('heading', { name: 'SummitFlow' }),
    ).toBeInTheDocument()
  })

  it('renders repository links and images with safe URLs and skips raw HTML', async () => {
    apiMocks.fetchProjectReadme.mockResolvedValue({
      project_id: 'summitflow',
      status: 'available',
      content:
        '[Guide](docs/guide.md)\n\n![Diagram](assets/diagram.png)\n\n[Unsafe](javascript:alert%281%29)\n\n<script>alert(1)</script>',
    })
    renderOverview()
    expect(await screen.findByRole('link', { name: 'Guide' })).toHaveAttribute(
      'href',
      '/projects/summitflow/files?path=docs%2Fguide.md',
    )
    expect(screen.getByAltText('Diagram').getAttribute('src')).toContain(
      '/api/projects/summitflow/files/download?path=assets%2Fdiagram.png',
    )
    expect(
      screen.queryByRole('link', { name: 'Unsafe' }),
    ).not.toBeInTheDocument()
    expect(document.querySelector('script')).toBeNull()
  })
})
