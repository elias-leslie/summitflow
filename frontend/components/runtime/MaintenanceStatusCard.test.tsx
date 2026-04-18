import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { MaintenanceStatusCard } from './MaintenanceStatusCard'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
}))

describe('MaintenanceStatusCard', () => {
  it('renders routine upkeep summary in collapsed state', () => {
    queryMocks.useQuery.mockReturnValue({
      data: {
        latest: {
          routine_upkeep: {
            id: 10,
            workflow_name: 'routine_upkeep',
            status: 'completed',
            started_at: '2026-04-10T16:00:00Z',
            finished_at: '2026-04-10T16:01:00Z',
            duration_ms: 60_000,
            rows_cleaned: 2,
            summary: { tasks_created: 2, dispatch: { dispatched: 2 } },
            error_message: null,
            created_at: '2026-04-10T16:00:00Z',
          },
        },
        recent: [],
      },
      error: undefined,
      isLoading: false,
    })

    render(<MaintenanceStatusCard />)

    expect(screen.getByText('Maintenance')).toBeInTheDocument()
    expect(
      screen.getByText('Routine upkeep completed · 2 tasks'),
    ).toBeInTheDocument()
  })

  it('shows latest workflow details when expanded', () => {
    queryMocks.useQuery.mockReturnValue({
      data: {
        latest: {
          routine_upkeep: {
            id: 10,
            workflow_name: 'routine_upkeep',
            status: 'failed',
            started_at: '2026-04-10T16:00:00Z',
            finished_at: '2026-04-10T16:01:00Z',
            duration_ms: 60_000,
            rows_cleaned: 0,
            summary: { source_errors: { feedback: 'Agent Hub unavailable' } },
            error_message: 'Agent Hub unavailable',
            created_at: '2026-04-10T16:00:00Z',
          },
          daily_maintenance: {
            id: 11,
            workflow_name: 'daily_maintenance',
            status: 'success',
            started_at: '2026-04-10T04:00:00Z',
            finished_at: '2026-04-10T04:01:00Z',
            duration_ms: 60_000,
            rows_cleaned: 9,
            summary: {},
            error_message: null,
            created_at: '2026-04-10T04:00:00Z',
          },
        },
        recent: [],
      },
      error: undefined,
      isLoading: false,
    })

    render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByText('Maintenance'))

    expect(screen.getByText('Routine Upkeep')).toBeInTheDocument()
    expect(screen.getByText('Daily Maintenance')).toBeInTheDocument()
    expect(screen.getByText('Agent Hub unavailable')).toBeInTheDocument()
  })

  it('keeps expanded empty history explicit', () => {
    queryMocks.useQuery.mockReturnValue({
      data: {
        latest: {},
        recent: [],
      },
      error: undefined,
      isLoading: false,
    })

    render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByText('Maintenance'))

    expect(screen.getByText('Routine upkeep never run')).toBeInTheDocument()
    expect(
      screen.getByText('No maintenance runs recorded yet.'),
    ).toBeInTheDocument()
  })
})
