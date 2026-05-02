import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProjectWithStats } from '@/lib/api'
import { ProjectCard } from './ProjectCard'

const pushMock = vi.fn()
const apiMocks = vi.hoisted(() => ({
  fetchProjectHealth: vi.fn(),
  fetchQualityGateHealth: vi.fn(),
}))
const checkpointMocks = vi.hoisted(() => ({
  getActiveCheckpoint: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock('next/image', () => ({
  default: () => <span data-testid="next-image" aria-hidden="true" />,
}))

vi.mock('@/lib/api', () => ({
  fetchProjectHealth: apiMocks.fetchProjectHealth,
  fetchQualityGateHealth: apiMocks.fetchQualityGateHealth,
}))

vi.mock('@/lib/api/checkpoints', () => ({
  getActiveCheckpoint: checkpointMocks.getActiveCheckpoint,
}))

function renderCard(project: ProjectWithStats) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectCard project={project} />
    </QueryClientProvider>,
  )
}

describe('ProjectCard', () => {
  const project: ProjectWithStats = {
    id: 'summitflow',
    name: 'SummitFlow',
    base_url: 'http://localhost:3001',
    public_url: 'https://public.example.test',
    health_endpoint: '/health',
    root_path: '/home/testuser/summitflow',
    category: 'production',
    sidebar_rank: 0,
    created_at: '2026-03-10T12:00:00Z',
    stats: {
      features: 3,
      tasks: 7,
      bugs: 2,
      blocked: 1,
    },
  }

  beforeEach(() => {
    pushMock.mockReset()
    apiMocks.fetchProjectHealth.mockResolvedValue({
      project_id: 'summitflow',
      healthy: true,
      response_time_ms: 42,
      checked_at: '2026-03-12T09:00:00Z',
    })
    apiMocks.fetchQualityGateHealth.mockResolvedValue({
      project_id: 'summitflow',
      overall_pass: false,
      total_unfixed: 3,
      checks: {},
    })
    checkpointMocks.getActiveCheckpoint.mockResolvedValue(null)
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('routes feature counts into the tasks view with the feature filter', () => {
    renderCard(project)

    fireEvent.click(screen.getByRole('button', { name: 'Features: 3' }))

    expect(pushMock).toHaveBeenCalledWith(
      '/projects/summitflow?tab=tasks&status=active&taskType=feature',
    )
  })

  it('shows the project host and root path trust signals', () => {
    renderCard(project)

    expect(screen.getByText('public.example.test')).toBeInTheDocument()
    expect(screen.getByTitle('/home/testuser/summitflow')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'SummitFlow' })).toHaveAttribute(
      'href',
      '/projects/summitflow',
    )
    expect(screen.getByRole('link', { name: /settings/i })).toHaveAttribute(
      'href',
      '/projects/summitflow/settings',
    )
    expect(screen.getByRole('link', { name: /open app/i })).toHaveAttribute(
      'href',
      'https://public.example.test',
    )
  })

  it('surfaces live service and quality summaries after hover loads checks', async () => {
    renderCard(project)

    fireEvent.mouseEnter(screen.getByRole('article'))

    expect(await screen.findByText('Service: 42ms')).toBeInTheDocument()
    expect(screen.getByText('Quality: 3 open')).toBeInTheDocument()
  })

  it('flags projects that are missing a root path', () => {
    renderCard({
      ...project,
      root_path: undefined,
    })

    expect(screen.getByText('No root path')).toBeInTheDocument()
  })
})
