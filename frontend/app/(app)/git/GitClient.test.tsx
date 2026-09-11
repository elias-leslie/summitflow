import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GitClient } from './GitClient'

const hookMocks = vi.hoisted(() => ({
  useGitStatus: vi.fn(),
  checkGitRemotes: vi.fn(),
}))

vi.mock('./useGitStatus', () => ({
  useGitStatus: hookMocks.useGitStatus,
}))

vi.mock('@/components/git/ConflictAlerts', () => ({
  ConflictAlerts: () => <div data-testid="conflict-alerts" />,
}))

vi.mock('@/components/git/ProjectRow', () => ({
  ProjectRow: ({
    repo,
    remoteCheckedAt,
  }: {
    repo: { name: string }
    remoteCheckedAt?: Date | null
  }) => (
    <div data-testid="project-row">
      {repo.name}: {remoteCheckedAt ? 'checked' : 'unchecked'}
    </div>
  ),
}))

vi.mock('@/lib/api', () => ({
  checkGitRemotes: hookMocks.checkGitRemotes,
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
      <GitClient />
    </QueryClientProvider>,
  )
}

describe('GitClient', () => {
  it('derives the header pills from repo workspace summaries', () => {
    hookMocks.useGitStatus.mockReturnValue({
      data: {
        repositories: [
          {
            path: '/srv/workspaces/projects/summitflow',
            name: 'summitflow',
            project_id: 'summitflow',
            branch: 'main',
            uncommitted: 0,
            ahead: 0,
            behind: 0,
            state: 'clean',
            workspace_summary: {
              active_checkpoints: 5,
              dirty_checkpoints: 1,
              dirty_main_repo: true,
              branches_with_checkpoints: 3,
              orphan_branches: 2,
              prunable_branches: 1,
              needs_cleanup: true,
              checkpoint_task_ids: ['task-1'],
            },
          },
          {
            path: '/srv/workspaces/projects/agent-hub',
            name: 'agent-hub',
            project_id: 'agent-hub',
            branch: 'main',
            uncommitted: 0,
            ahead: 1,
            behind: 0,
            state: 'ahead',
            workspace_summary: {
              active_checkpoints: 10,
              dirty_checkpoints: 8,
              dirty_main_repo: false,
              branches_with_checkpoints: 8,
              orphan_branches: 1,
              prunable_branches: 3,
              needs_cleanup: true,
              checkpoint_task_ids: ['task-2'],
            },
          },
        ],
      },
      isLoading: false,
      isError: false,
    })

    renderClient()

    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
  })
})

const cleanRepo = {
  path: '/repos/alpha',
  name: 'alpha',
  branch: 'main',
  uncommitted: 0,
  ahead: 0,
  behind: 0,
  state: 'clean',
}

it('shows remote-only debt instead of claiming all repos clean', () => {
  hookMocks.useGitStatus.mockReturnValue({
    data: { repositories: [{ ...cleanRepo, behind: 2, state: 'behind' }] },
    isLoading: false,
    isError: false,
  })
  renderClient()
  expect(screen.queryByText('All repos clean')).not.toBeInTheDocument()
  expect(screen.getByText('remote')).toBeInTheDocument()
})

it('does not claim all repos clean when status is unavailable', () => {
  hookMocks.useGitStatus.mockReturnValue({
    data: undefined,
    isLoading: false,
    isError: true,
  })
  renderClient()
  expect(screen.queryByText('All repos clean')).not.toBeInTheDocument()
})

it('marks only successful remote checks fresh and displays failures', async () => {
  hookMocks.useGitStatus.mockReturnValue({
    data: {
      repositories: [
        cleanRepo,
        { ...cleanRepo, path: '/repos/beta', name: 'beta' },
      ],
    },
    isLoading: false,
    isError: false,
  })
  hookMocks.checkGitRemotes.mockResolvedValue({
    results: [
      {
        path: '/repos/alpha',
        name: 'alpha',
        branch: 'main',
        status: 'updated',
      },
      {
        path: '/repos/beta',
        name: 'beta',
        branch: 'main',
        status: 'failed',
        error: 'Remote unavailable',
      },
    ],
    success: 1,
    failed: 1,
    skipped: 0,
  })
  renderClient()
  fireEvent.click(screen.getByRole('button', { name: 'Check Remote' }))
  await waitFor(() =>
    expect(screen.getByText(/beta: Remote unavailable/)).toBeInTheDocument(),
  )
  expect(screen.getByText('alpha: checked')).toBeInTheDocument()
  expect(screen.getByText('beta: unchecked')).toBeInTheDocument()
})
