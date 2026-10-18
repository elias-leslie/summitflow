import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { MaintenanceStatusCard } from './MaintenanceStatusCard'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('./CleanupSettings', () => ({ CleanupSettings: () => null }))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
}))

function run(
  workflow_name: string,
  status: string,
  started_at: string,
  extra: Record<string, unknown> = {},
) {
  return {
    id: 1,
    workflow_name,
    status,
    started_at,
    finished_at: null,
    duration_ms: 60_000,
    rows_cleaned: 0,
    summary: {},
    error_message: null,
    created_at: started_at,
    ...extra,
  }
}

function mockLatest(latest: Record<string, ReturnType<typeof run>>) {
  queryMocks.useQuery.mockReturnValue({
    data: { latest, recent: [] },
    error: undefined,
    isLoading: false,
  })
}

describe('MaintenanceStatusCard', () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-10-10T12:00:00Z'))
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('summarizes every workflow with the newest run age when all succeed', () => {
    mockLatest({
      daily_maintenance: run(
        'daily_maintenance',
        'success',
        '2026-10-10T04:00:00Z',
      ),
      scheduled_backups: run(
        'scheduled_backups',
        'completed',
        '2026-10-10T11:30:00Z',
      ),
    })

    const { container } = render(<MaintenanceStatusCard />)

    expect(
      screen.getByText('All workflows succeeded · last run 30m ago'),
    ).toBeInTheDocument()
    expect(container.querySelector('.bg-emerald-500')).not.toBeNull()
  })

  it('colors the dot by the worst current status, not one workflow', () => {
    mockLatest({
      daily_maintenance: run(
        'daily_maintenance',
        'success',
        '2026-10-10T04:00:00Z',
      ),
      scheduled_backups: run(
        'scheduled_backups',
        'partial',
        '2026-10-10T11:00:00Z',
      ),
      runtime_hygiene: run(
        'runtime_hygiene',
        'failed',
        '2026-10-10T10:00:00Z',
        { error_message: 'docker unavailable' },
      ),
    })

    const { container } = render(<MaintenanceStatusCard />)

    expect(
      screen.getByText('1 partial, 1 failed · last run 1h ago'),
    ).toBeInTheDocument()
    expect(container.querySelector('.bg-rose-500')).not.toBeNull()
  })

  it('shows start age and rows cleaned per workflow when expanded', () => {
    mockLatest({
      daily_maintenance: run(
        'daily_maintenance',
        'success',
        '2026-10-10T04:00:00Z',
        { rows_cleaned: 138 },
      ),
      runtime_hygiene: run(
        'runtime_hygiene',
        'failed',
        '2026-10-10T10:00:00Z',
        { error_message: 'docker unavailable' },
      ),
    })

    render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByText('Maintenance'))

    expect(screen.getByText('Daily Maintenance')).toBeInTheDocument()
    expect(screen.getByText('138 rows cleaned')).toBeInTheDocument()
    expect(screen.getByText('Started 8h ago · took 1.0m')).toBeInTheDocument()
    expect(screen.getByText('docker unavailable')).toBeInTheDocument()
    expect(screen.queryByText(/tasks/)).toBeNull()
  })

  it('keeps expanded empty history explicit', () => {
    mockLatest({})

    render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByText('Maintenance'))

    expect(screen.getByText('No runs recorded')).toBeInTheDocument()
    expect(
      screen.getByText('No maintenance runs recorded yet.'),
    ).toBeInTheDocument()
  })

  it('shows freed space for an emergency reclaim and a placeholder before the first one', () => {
    mockLatest({
      daily_maintenance: run(
        'daily_maintenance',
        'success',
        '2026-10-10T04:00:00Z',
      ),
    })
    const { unmount } = render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByRole('button'))
    expect(
      screen.getByText(
        'Not needed yet. Nightshift runs it when a disk is nearly full.',
      ),
    ).toBeInTheDocument()
    unmount()

    mockLatest({
      emergency_reclaim: run(
        'emergency_reclaim',
        'success',
        '2026-10-10T11:00:00Z',
        {
          rows_cleaned: 3,
          summary: { freed_bytes: 3 * 1024 ** 3, filesystem: '/' },
        },
      ),
    })
    render(<MaintenanceStatusCard />)
    fireEvent.click(screen.getByRole('button'))
    expect(
      screen.getByText('Freed 3.0 GB on / · 3 items removed'),
    ).toBeInTheDocument()
  })
})
