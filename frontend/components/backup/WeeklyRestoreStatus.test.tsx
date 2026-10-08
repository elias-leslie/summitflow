import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  BackupHealthResponse,
  CriticalRestoreHealth,
} from '@/lib/api/backups'
import { WeeklyRestoreStatus } from './WeeklyRestoreStatus'

const restore: CriticalRestoreHealth = {
  status: 'verified',
  last_success_at: '2026-10-01T10:00:00Z',
  latest_attempt: {
    status: 'verified',
    attempted_at: '2026-10-01T10:00:00Z',
    completed_at: '2026-10-01T10:02:00Z',
    failed_source_id: null,
    reason: null,
    cached: false,
  },
  required_source_ids: ['configuration', 'infrastructure'],
  verified_source_ids: ['configuration', 'infrastructure'],
  missing_source_ids: [],
}
const health: BackupHealthResponse = {
  sources: [],
  pending_upload_count: 0,
  repositories: [
    {
      backend_id: 'drive',
      backend_name: 'Offsite repository',
      critical_restore: restore,
    },
  ],
}
const props = { health, isLoading: false, error: null, onRefresh: () => {} }

function withRestore(value: CriticalRestoreHealth): BackupHealthResponse {
  return {
    ...health,
    repositories: [{ ...health.repositories![0], critical_restore: value }],
  }
}

describe('WeeklyRestoreStatus', () => {
  it('shows loading, unavailable and empty repository states distinctly', () => {
    const { rerender } = render(
      <WeeklyRestoreStatus {...props} health={undefined} isLoading />,
    )
    expect(screen.getByRole('status')).toHaveTextContent(
      'Loading weekly restore status',
    )
    expect(screen.queryByText('Passed')).not.toBeInTheDocument()
    rerender(
      <WeeklyRestoreStatus
        {...props}
        health={{ sources: [], pending_upload_count: 0 }}
      />,
    )
    expect(
      screen.getByText('Weekly restore status is unavailable.'),
    ).toBeInTheDocument()
    rerender(
      <WeeklyRestoreStatus
        {...props}
        health={{ ...health, repositories: [] }}
      />,
    )
    expect(
      screen.getByText(
        'No backup repositories are configured for the weekly restore.',
      ),
    ).toBeInTheDocument()
  })

  it('shows an earlier success alongside a current cached failure and its source', () => {
    render(
      <WeeklyRestoreStatus
        {...props}
        health={withRestore({
          ...restore,
          status: 'failed',
          latest_attempt: {
            ...restore.latest_attempt!,
            status: 'failed',
            failed_source_id: 'configuration',
            reason: 'mapped-links-unresolved',
            cached: true,
            completed_at: '2026-10-08T10:02:00Z',
          },
        })}
      />,
    )
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(screen.getByText(/Last passed:/)).toHaveTextContent('Oct 1')
    expect(
      screen.getByText('Required configuration links could not be restored.'),
    ).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'configuration' })).toHaveAttribute(
      'href',
      '/backups/configuration',
    )
    expect(screen.getByText(/Latest attempt:/)).toHaveTextContent(
      'Saved failure; unchanged inputs have not been retried.',
    )
    expect(
      screen.getByText('Last passed sources:').nextElementSibling,
    ).toHaveTextContent('configuration, infrastructure')
    expect(
      screen.getByText(/Host boot recovery is a separate check/),
    ).toBeInTheDocument()
  })

  it('keeps an unresolved failure visible while a repair is running', () => {
    render(
      <WeeklyRestoreStatus
        {...props}
        health={withRestore({
          ...restore,
          status: 'failed',
          latest_attempt: {
            ...restore.latest_attempt!,
            status: 'running',
            completed_at: null,
          },
        })}
      />,
    )
    expect(screen.getByText('Failed')).toBeInTheDocument()
    expect(
      screen.getByText(
        'Latest attempt is recorded as running; the previous failure remains unresolved.',
      ),
    ).toBeInTheDocument()
    expect(screen.getByText(/Latest attempt: Running/)).toBeInTheDocument()
  })

  it.each([
    ['verified', 'Passed'],
    ['pending', 'Pending'],
    ['running', 'Running'],
    ['stale', 'Overdue'],
    ['untested', 'Not tested'],
    ['unavailable', 'Unavailable'],
  ] as const)('labels the %s result explicitly', (status, label) => {
    render(
      <WeeklyRestoreStatus
        {...props}
        health={withRestore({ ...restore, status, latest_attempt: null })}
      />,
    )
    expect(screen.getByText(label)).toBeInTheDocument()
  })

  it('makes a fetch failure explicit and retries the real query', () => {
    const onRefresh = vi.fn()
    render(
      <WeeklyRestoreStatus
        {...props}
        health={undefined}
        error={new Error('Request failed')}
        onRefresh={onRefresh}
      />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Weekly restore status is unavailable.',
    )
    expect(screen.queryByText('Passed')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Retry backup health' }))
    expect(onRefresh).toHaveBeenCalledOnce()
  })

  it('qualifies retained results after a failed refresh', () => {
    render(
      <WeeklyRestoreStatus {...props} error={new Error('Request failed')} />,
    )
    expect(screen.getByRole('alert')).toHaveTextContent(
      'Showing the last received results.',
    )
    expect(screen.getByText('Passed')).toBeInTheDocument()
  })
})
