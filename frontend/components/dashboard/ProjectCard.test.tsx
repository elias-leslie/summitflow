import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { ProjectWithStats } from '@/lib/api'
import { ProjectCard } from './ProjectCard'

const pushMock = vi.fn()

vi.mock('next/navigation', () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}))

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('next/image', () => ({
  default: () => <span data-testid="next-image" aria-hidden="true" />,
}))

vi.mock('@/lib/api', () => ({
  fetchProjectHealth: vi.fn(),
  fetchQualityGateHealth: vi.fn(),
}))

vi.mock('@/lib/api/checkpoints', () => ({
  getActiveCheckpoint: vi.fn(),
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
    base_url: 'https://dev.summitflow.dev',
    health_endpoint: '/health',
    root_path: '/home/kasadis/summitflow',
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

    expect(screen.getByText('dev.summitflow.dev')).toBeInTheDocument()
    expect(screen.getByTitle('/home/kasadis/summitflow')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'SummitFlow' })).toHaveAttribute(
      'href',
      '/projects/summitflow',
    )
  })
})
