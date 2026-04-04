import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Project } from '@/lib/api'
import { ProjectOverview } from './ProjectOverview'

const apiMocks = vi.hoisted(() => ({
  fetchProjectHealth: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  fetchProjectHealth: apiMocks.fetchProjectHealth,
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
    apiMocks.fetchProjectHealth.mockResolvedValue({
      project_id: 'summitflow',
      healthy: true,
      response_time_ms: 42,
      checked_at: '2026-04-04T12:00:00Z',
    })
  })

  it('renders the public service status surface and project-scoped recent activity', async () => {
    renderOverview()

    expect(await screen.findByText('42ms response time')).toBeInTheDocument()
    expect(screen.getByText('Service Status')).toBeInTheDocument()
    expect(screen.getByText('Recent Activity')).toBeInTheDocument()
    expect(screen.getByTestId('activity-feed')).toHaveTextContent('Activity feed for summitflow')
    expect(screen.queryByText('Quality Summary')).not.toBeInTheDocument()
    expect(screen.queryByText('Workspace')).not.toBeInTheDocument()
    expect(screen.queryByText('Open Findings')).not.toBeInTheDocument()
  })

  it('shows health errors without exposing internal project metadata', async () => {
    apiMocks.fetchProjectHealth.mockResolvedValue({
      project_id: 'summitflow',
      healthy: false,
      error: 'connection refused',
      checked_at: '2026-04-04T12:00:00Z',
    })

    renderOverview()

    expect(await screen.findByText('connection refused')).toBeInTheDocument()
    expect(screen.queryByText('/srv/workspaces/projects/summitflow')).not.toBeInTheDocument()
  })
})
