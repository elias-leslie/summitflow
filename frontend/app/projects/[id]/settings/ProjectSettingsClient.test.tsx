import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectSettingsClient } from './ProjectSettingsClient'

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  fetchProject: vi.fn(),
  fetchProjectHealth: vi.fn(),
  fetchProjectServices: vi.fn(),
  fetchQualityGateHealth: vi.fn(),
  updateProject: vi.fn(),
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
  fetchProjectHealth: apiMocks.fetchProjectHealth,
  fetchProjectServices: apiMocks.fetchProjectServices,
  fetchQualityGateHealth: apiMocks.fetchQualityGateHealth,
  updateProject: apiMocks.updateProject,
}))

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
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
    apiMocks.fetchProjectHealth.mockResolvedValue({
      project_id: 'summitflow',
      healthy: true,
      response_time_ms: 123,
      checked_at: '2026-03-12T10:00:00Z',
    })
    apiMocks.fetchQualityGateHealth.mockResolvedValue({
      project_id: 'summitflow',
      overall_pass: false,
      total_unfixed: 3,
      checks: {},
    })
    apiMocks.fetchProjectServices.mockResolvedValue({
      project_id: 'summitflow',
      config_source: 'file',
      services: {
        backend: {
          name: 'backend',
          command: 'uv run uvicorn app.main:app --port {port}',
          port: 8001,
          worktree_port_base: 8101,
          worktree_port_range: 100,
          cwd: 'backend',
          env_file: '.env',
          build_command: null,
        },
      },
    })
    apiMocks.updateProject.mockResolvedValue({
      id: 'summitflow',
      name: 'SummitFlow Ops',
      base_url: 'https://dev.summitflow.dev',
      health_endpoint: '/healthz',
      root_path: '/home/kasadis/summitflow',
      created_at: '2026-03-12T09:00:00Z',
    })
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

  it('shows live project trust signals and service configuration', async () => {
    apiMocks.fetchProject.mockResolvedValue({
      id: 'summitflow',
      name: 'SummitFlow',
      base_url: 'https://dev.summitflow.dev',
      health_endpoint: '/health',
      root_path: '/home/kasadis/summitflow',
      created_at: '2026-03-12T09:00:00Z',
    })

    renderClient()

    expect(await screen.findByText('Project Settings')).toBeInTheDocument()
    expect(screen.getByDisplayValue('summitflow')).toBeInTheDocument()
    expect(await screen.findByText('123ms')).toBeInTheDocument()
    expect(await screen.findByText('3 open')).toBeInTheDocument()
    expect(await screen.findByText('.st/services.yaml detected')).toBeInTheDocument()
    expect(
      screen.getByText('uv run uvicorn app.main:app --port {port}'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('autonomous-settings')).toHaveTextContent(
      'summitflow',
    )
  })

  it('saves normalized registration changes', async () => {
    apiMocks.fetchProject.mockResolvedValue({
      id: 'summitflow',
      name: 'SummitFlow',
      base_url: 'https://dev.summitflow.dev',
      health_endpoint: '/health',
      root_path: '/home/kasadis/summitflow',
      created_at: '2026-03-12T09:00:00Z',
    })

    renderClient()

    expect(await screen.findByText('Project Settings')).toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: ' SummitFlow Ops ' },
    })
    fireEvent.change(screen.getByLabelText('Base URL *'), {
      target: { value: 'https://dev.summitflow.dev///' },
    })
    fireEvent.change(screen.getByLabelText('Health Endpoint'), {
      target: { value: 'healthz' },
    })
    fireEvent.change(screen.getByLabelText('Root Path'), {
      target: { value: '/home/kasadis/summitflow///' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }))

    await waitFor(() => {
      expect(apiMocks.updateProject).toHaveBeenCalledWith('summitflow', {
        name: 'SummitFlow Ops',
        base_url: 'https://dev.summitflow.dev',
        health_endpoint: '/healthz',
        root_path: '/home/kasadis/summitflow',
      })
    })
    expect(
      await screen.findByText('Project registration details saved.'),
    ).toBeInTheDocument()
  })
})
