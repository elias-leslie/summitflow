import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { DashboardClient } from './DashboardClient'

const apiMocks = vi.hoisted(() => ({
  fetchProjectsWithStats: vi.fn(),
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

vi.mock('@/hooks/usePersonaName', () => ({
  usePersonaName: () => 'Jenny',
}))

vi.mock('@/components/dashboard', () => ({
  ActivityFeed: () => <div data-testid="activity-feed" />,
  ProjectCard: ({ project }: { project: { name: string } }) => (
    <div>{project.name}</div>
  ),
  SystemHealthWidget: () => <div data-testid="system-health-widget" />,
}))

vi.mock('@/lib/api', () => ({
  fetchProjectsWithStats: apiMocks.fetchProjectsWithStats,
}))

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardClient />
    </QueryClientProvider>,
  )
}

describe('DashboardClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.fetchProjectsWithStats.mockResolvedValue({
      total: 1,
      projects: [
        {
          id: 'summitflow',
          name: 'SummitFlow',
          base_url: 'https://dev.summitflow.dev',
          health_endpoint: '/health',
          created_at: '2026-03-12T12:00:00Z',
          stats: {
            features: 2,
            tasks: 3,
            bugs: 1,
            blocked: 1,
          },
        },
      ],
    })
  })

  it('surfaces feature totals in the dashboard summary', async () => {
    renderClient()

    const featureLabel = await screen.findByText('Active Features')
    await screen.findByText('SummitFlow')

    expect(featureLabel).toBeInTheDocument()
    expect(featureLabel.parentElement).toHaveTextContent('2')
    expect(screen.getByText('Active Tasks')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Hover, focus, or tap a card to load live health and quality signals for that project.',
      ),
    ).toBeInTheDocument()
  })
})
