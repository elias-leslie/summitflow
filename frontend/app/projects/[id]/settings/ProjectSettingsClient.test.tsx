import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectSettingsClient } from './ProjectSettingsClient'

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  fetchProject: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useParams: navigationMocks.useParams,
}))

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: React.ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/components/settings/AutonomousSettings', () => ({
  AutonomousSettingsPanel: ({ projectId }: { projectId: string }) => (
    <div data-testid="autonomous-settings">{projectId}</div>
  ),
}))

vi.mock('@/lib/api', () => ({
  fetchProject: apiMocks.fetchProject,
}))

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectSettingsClient />
    </QueryClientProvider>,
  )
}

describe('ProjectSettingsClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    navigationMocks.useParams.mockReturnValue({ id: 'summitflow' })
  })

  it('surfaces fetch errors with recovery links', async () => {
    apiMocks.fetchProject.mockRejectedValue(new Error('backend unavailable'))

    renderClient()

    await waitFor(() => {
      expect(
        screen.getByText('Unable to load project settings'),
      ).toBeInTheDocument()
    })
    expect(screen.getByText('backend unavailable')).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Back to project' })).toHaveAttribute(
      'href',
      '/projects/summitflow',
    )
  })

  it('shows project trust signals alongside autonomous settings', async () => {
    apiMocks.fetchProject.mockResolvedValue({
      id: 'summitflow',
      name: 'SummitFlow',
      base_url: 'https://dev.summitflow.dev',
      health_endpoint: '/api/health',
      root_path: '/home/kasadis/summitflow',
      created_at: '2026-03-12T09:00:00Z',
    })

    renderClient()

    expect(await screen.findByText('Project Settings')).toBeInTheDocument()
    expect(screen.getByText('https://dev.summitflow.dev')).toBeInTheDocument()
    expect(screen.getByText('/home/kasadis/summitflow')).toBeInTheDocument()
    expect(screen.getByTestId('autonomous-settings')).toHaveTextContent(
      'summitflow',
    )
  })
})
