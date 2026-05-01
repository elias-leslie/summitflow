import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GitClient } from './GitClient'

const hookMocks = vi.hoisted(() => ({
  useGitStatus: vi.fn(),
}))

vi.mock('./useGitStatus', () => ({
  useGitStatus: hookMocks.useGitStatus,
}))

vi.mock('@/components/git/ConflictAlerts', () => ({
  ConflictAlerts: () => <div data-testid="conflict-alerts" />,
}))

vi.mock('@/components/git/ProjectRow', () => ({
  ProjectRow: ({ repo }: { repo: { name: string } }) => (
    <div data-testid="project-row">{repo.name}</div>
  ),
}))

vi.mock('@/lib/api', () => ({
  checkGitRemotes: vi.fn(),
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
              task_branches: 4,
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
              task_branches: 9,
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
