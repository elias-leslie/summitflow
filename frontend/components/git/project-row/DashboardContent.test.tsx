import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { DashboardContent } from './DashboardContent'

const apiMocks = vi.hoisted(() => ({
  fetchProjectDashboard: vi.fn(),
}))

vi.mock('@/lib/api/git-enhanced', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/git-enhanced')>(
    '@/lib/api/git-enhanced',
  )

  return {
    ...actual,
    fetchProjectDashboard: apiMocks.fetchProjectDashboard,
  }
})

function renderContent() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <DashboardContent projectId="project-alpha" />
    </QueryClientProvider>,
  )
}

describe('DashboardContent', () => {
  it('renders branch and worktree sections from the project dashboard', async () => {
    apiMocks.fetchProjectDashboard.mockResolvedValue({
      worktrees: [
        {
          task_id: 'task-123',
          path: '/home/testuser/.local/share/st/worktrees/project-alpha/task-123',
          branch: 'task-123/main',
          base_branch: 'main',
          is_active: true,
          project_id: 'project-alpha',
        },
      ],
      branches: [
        {
          name: 'task-123/main',
          is_current: false,
          has_worktree: true,
          repo_name: 'repo-folder',
          project_id: 'project-alpha',
          worktree_path:
            '/home/testuser/.local/share/st/worktrees/project-alpha/task-123',
          task_id: 'task-123',
          last_commit_short: 'abc1234',
          last_commit_date: '2026-03-17T10:00:00Z',
        },
      ],
      recent_merges: [],
      recent_commits: [],
      snapshots: [],
      conflicts: [],
    })

    renderContent()

    expect(
      await screen.findByText('Worktrees', { selector: 'span' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Branches', { selector: 'span' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('task-123/main')).toHaveLength(2)
    expect(
      screen.getByText('Worktree', { selector: 'span' }),
    ).toBeInTheDocument()
  })
})
