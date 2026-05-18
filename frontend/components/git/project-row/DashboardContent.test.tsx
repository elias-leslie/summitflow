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
  it('renders branch and checkout sections from the project dashboard', async () => {
    apiMocks.fetchProjectDashboard.mockResolvedValue({
      checkpoints: [
        {
          task_id: 'task-123',
          path: '/home/testuser//.local/share/st/checkpoints/project-alpha/task-123',
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
          has_checkpoint: false,
          repo_name: 'repo-folder',
          project_id: 'project-alpha',
          checkout_path:
            '/home/testuser//.local/share/st/checkpoints/project-alpha/task-123',
          task_id: 'task-123',
          last_commit_short: 'abc1234',
          last_commit_date: '2026-03-17T10:00:00Z',
          cleanup_resolution: 'review',
          task_status: 'running',
          commits_ahead: 2,
          files_changed: 5,
        },
      ],
      recent_merges: [],
      recent_commits: [],
      snapshots: [],
      conflicts: [],
    })

    renderContent()

    expect(
      await screen.findByText('Checkpoints', { selector: 'span' }),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Branches', { selector: 'span' }),
    ).toBeInTheDocument()
    expect(screen.getAllByText('task-123/main')).toHaveLength(1)
    expect(screen.getByText('Review')).toBeInTheDocument()
    expect(
      screen.getByText('task running / 2 ahead / 5 files'),
    ).toBeInTheDocument()
  })
})
