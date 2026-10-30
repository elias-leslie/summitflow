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
  fetchProjectRegistrationDefaults: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: routerMocks.useRouter,
}))

vi.mock('@/lib/api', () => ({
  createProject: apiMocks.createProject,
  fetchProjectRegistrationDefaults: apiMocks.fetchProjectRegistrationDefaults,
  PROJECT_CATEGORY_LABELS: {
    production: 'Production',
    testing: 'Testing',
    dev: 'Dev',
  },
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

async function submitProject() {
  fireEvent.click(screen.getByRole('button', { name: 'Create Project' }))

  await waitFor(() => {
    expect(apiMocks.createProject).toHaveBeenCalled()
  })
  return apiMocks.createProject.mock.calls[0]?.[0]
}

describe('NewProjectClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routerMocks.useRouter.mockReturnValue({ push: routerMocks.push })
    apiMocks.createProject.mockResolvedValue({
      id: 'my-project',
      name: 'My Project',
    })
    apiMocks.fetchProjectRegistrationDefaults.mockResolvedValue({
      managed_projects_root: '/data/hosted/projects',
    })
  })

  it('normalizes project registration fields before submitting', async () => {
    renderClient()

    expect(screen.queryByLabelText('Permission Tier')).not.toBeInTheDocument()
    expect(
      screen.queryByLabelText('Provision Agent Hub permission'),
    ).not.toBeInTheDocument()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'My Project!!' },
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
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

    expect(await submitProject()).toEqual({
      id: 'my-project',
      name: 'My Project!!',
      base_url: 'https://example.com',
      health_endpoint: '/healthz',
      root_path: '/tmp/my-project',
      category: 'dev',
      summitflow_hosted: undefined,
      agent_hub_permission: {},
      onboarding: {},
    })
  })

  it('auto-fills the managed workspace root and marks hosted setup on submit', async () => {
    renderClient()

    expect(
      await screen.findByText('/data/hosted/projects/<project-id>'),
    ).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'Hosted Example' },
    })

    expect(screen.getByLabelText('Root Path')).toHaveValue(
      '/data/hosted/projects/hosted-example',
    )

    expect(await submitProject()).toEqual({
      id: 'hosted-example',
      name: 'Hosted Example',
      base_url: undefined,
      health_endpoint: '/health',
      root_path: '/data/hosted/projects/hosted-example',
      category: 'dev',
      summitflow_hosted: true,
      agent_hub_permission: {},
      onboarding: {},
    })
  })

  it('fills the managed root once it loads after the name was typed', async () => {
    let resolveDefaults: (value: { managed_projects_root: string }) => void =
      () => {}
    apiMocks.fetchProjectRegistrationDefaults.mockReturnValue(
      new Promise((resolve) => {
        resolveDefaults = resolve
      }),
    )
    renderClient()

    expect(
      screen.getByText(
        /Loading the default folder for SummitFlow-hosted projects/,
      ),
    ).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'Early Bird' },
    })
    expect(screen.getByLabelText('Root Path')).toHaveValue('')

    resolveDefaults({ managed_projects_root: '/data/hosted/projects' })
    await waitFor(() => {
      expect(screen.getByLabelText('Root Path')).toHaveValue(
        '/data/hosted/projects/early-bird',
      )
    })
  })

  it('says the managed root failed to load and leaves the path to the user', async () => {
    apiMocks.fetchProjectRegistrationDefaults.mockRejectedValue(
      new Error('Failed to load project defaults'),
    )
    renderClient()

    expect(
      await screen.findByText(/Couldn't load the folder/),
    ).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'Hosted Example' },
    })
    expect(screen.getByLabelText('Root Path')).toHaveValue('')
  })

  it('blocks submission when the root path is relative', async () => {
    renderClient()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'My Project' },
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
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

  it('submits the selected sidebar category', async () => {
    renderClient()

    await screen.findByText('/data/hosted/projects/<project-id>')

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'Testing Project' },
    })
    fireEvent.change(screen.getByLabelText('Base URL'), {
      target: { value: 'https://example.com' },
    })
    fireEvent.click(screen.getByLabelText('Sidebar Category'))
    fireEvent.click(screen.getByRole('button', { name: 'Testing' }))

    expect(await submitProject()).toMatchObject({
      id: 'testing-project',
      category: 'testing',
      summitflow_hosted: true,
      onboarding: {},
    })
  })
})
