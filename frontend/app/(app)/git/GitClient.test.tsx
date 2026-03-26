import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { GitClient } from './GitClient'

const hookMocks = vi.hoisted(() => ({
  useGitStatus: vi.fn(),
  useGitCleanupStatus: vi.fn(),
}))

vi.mock('./useGitStatus', () => ({
  useGitStatus: hookMocks.useGitStatus,
  useGitCleanupStatus: hookMocks.useGitCleanupStatus,
}))

vi.mock('@/components/git/ConflictAlerts', () => ({
  ConflictAlerts: () => <div data-testid="conflict-alerts" />,
}))

vi.mock('@/components/git/ProjectRow', () => ({
  ProjectRow: ({ repo }: { repo: { name: string } }) => (
    <div data-testid="project-row">{repo.name}</div>
  ),
}))

describe('GitClient', () => {
  it('uses canonical cleanup summary counts for the header pills', () => {
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
              active_worktrees: 3,
              dirty_worktrees: 1,
              dirty_main_repo: true,
              branches_with_worktrees: 3,
              task_branches: 2,
              orphan_branches: 0,
              prunable_branches: 0,
              needs_cleanup: true,
              worktree_task_ids: ['task-1'],
            },
          },
        ],
      },
      isLoading: false,
      isError: false,
    })
    hookMocks.useGitCleanupStatus.mockReturnValue({
      data: {
        payload: {
          summary: {
            repos: 8,
            repos_needing_cleanup: 7,
            active_worktrees: 15,
            dirty_worktrees: 10,
            stale_checkpoints: 0,
            snapshot_residue: 1,
            orphan_task_branches: 1,
            prunable_task_branches: 1,
          },
          repositories: [],
          worktrees: [],
          total: 15,
        },
        compact: 'CLEANUP[all]:repos=8 needs_cleanup=7 worktrees=15 dirty=10',
      },
    })

    render(<GitClient />)

    expect(screen.getByText('10')).toBeInTheDocument()
    expect(screen.getByText('15')).toBeInTheDocument()
    expect(screen.getByText('7')).toBeInTheDocument()
  })
})
