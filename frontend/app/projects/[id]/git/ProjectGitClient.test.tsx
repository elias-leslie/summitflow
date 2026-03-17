import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectGitClient } from './ProjectGitClient'

const navigationMocks = vi.hoisted(() => ({
  useParams: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  fetchProjectGitStatus: vi.fn(),
  pullRepository: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useParams: navigationMocks.useParams,
}))

vi.mock('@/lib/api', () => ({
  fetchProjectGitStatus: apiMocks.fetchProjectGitStatus,
  pullRepository: apiMocks.pullRepository,
}))

vi.mock('@/components/git/ConflictAlerts', () => ({
  ConflictAlerts: ({ projectId }: { projectId?: string }) => (
    <div data-testid="conflict-alerts">{projectId}</div>
  ),
}))

vi.mock('@/components/git/project-row/DashboardContent', () => ({
  DashboardContent: ({ projectId }: { projectId: string }) => (
    <div data-testid="dashboard-content">{projectId}</div>
  ),
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
      <ProjectGitClient />
    </QueryClientProvider>,
  )
}

describe('ProjectGitClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    navigationMocks.useParams.mockReturnValue({ id: 'project-alpha' })
    apiMocks.fetchProjectGitStatus.mockResolvedValue({
      repositories: [
        {
          path: '/repos/repo-folder',
          name: 'repo-folder',
          project_id: 'project-alpha',
          branch: 'main',
          uncommitted: 0,
          ahead: 0,
          behind: 0,
          state: 'clean',
          workspace_summary: {
            active_worktrees: 1,
            dirty_worktrees: 0,
            branches_with_worktrees: 1,
            task_branches: 1,
            orphan_branches: 0,
            prunable_branches: 0,
            needs_cleanup: false,
            worktree_task_ids: ['task-123'],
          },
        },
      ],
      total: 1,
    })
    apiMocks.pullRepository.mockResolvedValue({
      results: [
        {
          path: '/repos/repo-folder',
          name: 'repo-folder',
          branch: 'main',
          status: 'updated',
        },
      ],
      success: 1,
      failed: 0,
      skipped: 0,
    })
  })

  it('uses project-scoped pull and passes the route project id to dependent sections', async () => {
    renderClient()

    expect(
      await screen.findByText('Project Git Operations'),
    ).toBeInTheDocument()
    expect(screen.getByTestId('conflict-alerts')).toHaveTextContent(
      'project-alpha',
    )
    expect(screen.getByTestId('dashboard-content')).toHaveTextContent(
      'project-alpha',
    )

    fireEvent.click(screen.getByRole('button', { name: /pull latest/i }))

    await waitFor(() => {
      expect(apiMocks.pullRepository).toHaveBeenCalledWith('project-alpha')
    })
  })
})
