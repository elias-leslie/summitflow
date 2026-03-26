import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ProjectRow } from './ProjectRow'

const apiMocks = vi.hoisted(() => ({
  smartSyncProject: vi.fn(),
}))

vi.mock('@/lib/api', () => ({
  smartSyncProject: apiMocks.smartSyncProject,
}))

vi.mock('./project-row/DashboardContent', () => ({
  DashboardContent: ({ projectId }: { projectId: string }) => (
    <div data-testid="dashboard-content">{projectId}</div>
  ),
}))

function renderRow() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectRow
        repo={{
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
            dirty_main_repo: true,
            branches_with_worktrees: 1,
            task_branches: 1,
            orphan_branches: 0,
            prunable_branches: 0,
            needs_cleanup: false,
            worktree_task_ids: ['task-123'],
          },
        }}
      />
    </QueryClientProvider>,
  )
}

function renderConfigRow() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectRow
        repo={{
          path: '/repos/.claude',
          name: '.claude',
          project_id: null,
          branch: 'main',
          uncommitted: 0,
          ahead: 0,
          behind: 0,
          state: 'clean',
          workspace_summary: {
            active_worktrees: 0,
            dirty_worktrees: 0,
            dirty_main_repo: false,
            branches_with_worktrees: 0,
            task_branches: 0,
            orphan_branches: 0,
            prunable_branches: 0,
            needs_cleanup: false,
            worktree_task_ids: [],
          },
        }}
      />
    </QueryClientProvider>,
  )
}

describe('ProjectRow', () => {
  it('uses project_id for sync and dashboard expansion', async () => {
    apiMocks.smartSyncProject.mockResolvedValue({
      success: true,
      status: 'updated',
      gates: '',
      errors: [],
      message: 'ok',
      reason: '',
      pushed: false,
      raw_output: 'ok',
    })

    renderRow()

    // Click the row header to expand
    const row = screen.getByRole('button', { name: /repo-folder/i })
    fireEvent.click(row)
    expect(screen.getByTestId('dashboard-content')).toHaveTextContent(
      'project-alpha',
    )

    // Click sync button (exact text match to avoid matching the row header)
    fireEvent.click(screen.getByRole('button', { name: 'Sync' }))

    await waitFor(() => {
      expect(apiMocks.smartSyncProject).toHaveBeenCalledWith('project-alpha')
    })
  })

  it('offers sync for config repos', () => {
    renderConfigRow()

    expect(
      screen.getByRole('button', { name: 'Sync' }),
    ).toBeInTheDocument()
  })
})
