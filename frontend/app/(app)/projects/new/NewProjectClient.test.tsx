import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewProjectClient } from './NewProjectClient'

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  useRouter: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  createProject: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: routerMocks.useRouter,
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

vi.mock('@/lib/api', () => ({
  createProject: apiMocks.createProject,
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
      <NewProjectClient />
    </QueryClientProvider>,
  )
}

describe('NewProjectClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routerMocks.useRouter.mockReturnValue({ push: routerMocks.push })
    apiMocks.createProject.mockResolvedValue({
      id: 'my-project',
      name: 'My Project',
    })
  })

  it('normalizes project registration fields before submitting', async () => {
    renderClient()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'My Project!!' },
    })
    fireEvent.change(screen.getByLabelText('Base URL *'), {
      target: { value: 'https://example.com///' },
    })
    fireEvent.change(screen.getByLabelText('Health Endpoint'), {
      target: { value: 'healthz' },
    })
    fireEvent.change(screen.getByLabelText('Root Path'), {
      target: { value: '/tmp/my-project///' },
    })

    expect(screen.getByText('https://example.com/healthz')).toBeInTheDocument()
    expect(screen.getByText('/tmp/my-project')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }))

    await waitFor(() => {
      expect(apiMocks.createProject).toHaveBeenCalled()
    })
    expect(apiMocks.createProject.mock.calls[0]?.[0]).toEqual({
      id: 'my-project',
      name: 'My Project!!',
      base_url: 'https://example.com',
      health_endpoint: '/healthz',
      root_path: '/tmp/my-project',
      agent_hub_permission: {
        permission_tier: 'read',
        auto_exec_enabled: false,
        execution_start_hour: 0,
        execution_end_hour: 24,
      },
    })
  })

  it('blocks submission when the root path is relative', async () => {
    renderClient()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'My Project' },
    })
    fireEvent.change(screen.getByLabelText('Base URL *'), {
      target: { value: 'https://example.com' },
    })
    fireEvent.change(screen.getByLabelText('Root Path'), {
      target: { value: 'relative/path' },
    })

    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }))

    expect(
      await screen.findByText('Root path must be an absolute path'),
    ).toBeInTheDocument()
    expect(apiMocks.createProject).not.toHaveBeenCalled()
  })

  it('allows skipping Agent Hub permission bootstrap', async () => {
    renderClient()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'No Bootstrap' },
    })
    fireEvent.change(screen.getByLabelText('Base URL *'), {
      target: { value: 'https://example.com' },
    })
    fireEvent.click(screen.getByLabelText('Provision Agent Hub permission'))
    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }))

    await waitFor(() => {
      expect(apiMocks.createProject).toHaveBeenCalled()
    })
    expect(apiMocks.createProject.mock.calls[0]?.[0]).toEqual({
      id: 'no-bootstrap',
      name: 'No Bootstrap',
      base_url: 'https://example.com',
      health_endpoint: '/health',
      root_path: undefined,
      agent_hub_permission: undefined,
    })
  })
})
