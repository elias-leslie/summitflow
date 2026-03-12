import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { RecentActivityCard } from './RecentActivityCard'

const activityMocks = vi.hoisted(() => ({
  fetchActivity: vi.fn(),
}))

vi.mock('@/lib/api/activity', () => ({
  fetchActivity: activityMocks.fetchActivity,
}))

function renderWithQueryClient(ui: React.ReactElement) {
  const client = new QueryClient({
    defaultOptions: {
      queries: {
        retry: false,
      },
    },
  })

  return render(
    <QueryClientProvider client={client}>
      {ui}
    </QueryClientProvider>,
  )
}

describe('RecentActivityCard', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('renders activity metadata when events load successfully', async () => {
    activityMocks.fetchActivity.mockResolvedValue({
      items: [
        {
          type: 'task',
          message: 'Task completed',
          timestamp: '2026-03-12T09:00:00Z',
          project_id: 'summitflow',
          metadata: {
            status: 'completed',
            agent_type: 'codex',
            tests_passed: 4,
            tests_failed: 1,
          },
        },
      ],
      total: 1,
      limit: 8,
      offset: 0,
      has_more: false,
    })

    renderWithQueryClient(<RecentActivityCard projectId="summitflow" />)

    expect(await screen.findByText('Task completed')).toBeInTheDocument()
    expect(screen.getByText('completed · codex · 4/1 tests')).toBeInTheDocument()
  })

  it('renders the query error message when loading fails', async () => {
    activityMocks.fetchActivity.mockRejectedValue(new Error('Activity endpoint timed out'))

    renderWithQueryClient(<RecentActivityCard projectId="summitflow" />)

    await waitFor(() => {
      expect(screen.getByText('Failed to load activity')).toBeInTheDocument()
    })
    expect(screen.getByText('Activity endpoint timed out')).toBeInTheDocument()
  })

  it('renders an explanatory empty state when there are no events', async () => {
    activityMocks.fetchActivity.mockResolvedValue({
      items: [],
      total: 0,
      limit: 8,
      offset: 0,
      has_more: false,
    })

    renderWithQueryClient(<RecentActivityCard projectId="summitflow" />)

    expect(await screen.findByText('No recent activity')).toBeInTheDocument()
    expect(
      screen.getByText('New task, git, session, and backup events will appear here.'),
    ).toBeInTheDocument()
  })
})
