import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  type BackupActivity,
  type BackupHealthItem,
  cancelBackup,
  syncBackupOffsite,
} from '@/lib/api/backups'
import { OffsiteStatus } from './OffsiteStatus'
import { SourceCard } from './SourceCard'

vi.mock('@/lib/api/backups', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/lib/api/backups')>()),
  cancelBackup: vi.fn(),
  syncBackupOffsite: vi.fn(),
}))

const health: BackupHealthItem = {
  source_id: 'source',
  source_name: 'Source',
  source_type: 'project',
  enabled: true,
  health_status: 'yellow',
  last_success_at: '2026-09-23T12:00:00Z',
  next_run_at: null,
  failure_count_7d: 0,
  pending_upload_count: 0,
  last_restore_tested_at: null,
  last_restore_test_ok: null,
  latest_backup_age_hours: 1,
  latest_restore_test_age_hours: null,
  restore_test_backup_id: null,
  coverage_complete: null,
  pitr_supported: false,
  restore_confidence: null,
  last_drill_at: null,
  last_drill_ok: null,
  last_drill_backup_id: null,
  latest_backup_id: 'saved-backup',
  offsite_status: 'failed',
  last_offsite_verified_at: null,
  offsite_location: null,
  offsite_checksum: null,
  offsite_error: 'Drive disconnected',
  last_isolated_restore_at: null,
  last_isolated_restore_ok: null,
}

const activity: BackupActivity = {
  backup_id: 'active-backup',
  run_id: 'run-1',
  active: true,
  phase: 'upload',
  operation_started_at: '2026-09-23T12:05:00Z',
  last_verified_at: null,
  last_verified_part: null,
  verified_parts: 0,
  attention: false,
  cancel_requested: false,
  remote_outcome_unknown: false,
}

describe('Backup recovery and activity status', () => {
  beforeEach(() => vi.resetAllMocks())

  it('keeps local success distinct from failed Drive sync and permits saved-archive retry', () => {
    render(<OffsiteStatus health={health} onSaved={() => {}} />)
    expect(screen.getByText('Last completed local backup')).toBeInTheDocument()
    expect(screen.getByText('Sync failed')).toBeInTheDocument()
    expect(screen.getByRole('alert')).toHaveTextContent('Drive disconnected')
    expect(
      screen.getByRole('button', { name: 'Sync saved backup to Drive' }),
    ).toBeEnabled()
    expect(
      screen.queryByText('Verified encrypted copy'),
    ).not.toBeInTheDocument()
  })

  it('does not offer a duplicate retry during an active opaque upload', () => {
    render(
      <OffsiteStatus
        health={{ ...health, backup_activity: activity }}
        onSaved={() => {}}
      />,
    )
    expect(screen.getByText('Uploading to Drive')).toBeInTheDocument()
    expect(screen.getByText(/Transfer progress is unknown/)).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sync saved backup to Drive' }),
    ).not.toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Cancel operation' }),
    ).toBeEnabled()
  })

  it('shows attention without calling a long wait failed or stalled, preserving verified part evidence', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          offsite_status: 'pending',
          backup_activity: {
            ...activity,
            attention: true,
            verified_parts: 2,
            last_verified_part: 'archive.age.part000002',
            last_verified_at: '2026-09-23T12:07:00Z',
          },
        }}
        onSaved={() => {}}
      />,
    )
    expect(
      screen.getByText('Waiting for Drive confirmation'),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/A long wait does not prove the transfer has stalled/),
    ).toBeInTheDocument()
    expect(screen.getByText(/2 parts verified by download/)).toBeInTheDocument()
    expect(screen.queryByText('Sync failed')).not.toBeInTheDocument()
    expect(
      screen.queryByText('Verified encrypted copy'),
    ).not.toBeInTheDocument()
  })

  it('shows capture separately and targets cancellation to the active backup and exact run', async () => {
    vi.mocked(cancelBackup).mockResolvedValue({
      task_id: 'run-1',
      status: 'cancelling',
      message: '',
    })
    const onSaved = vi.fn()
    const { rerender } = render(
      <OffsiteStatus
        health={{
          ...health,
          backup_activity: { ...activity, phase: 'capture' },
        }}
        onSaved={onSaved}
      />,
    )
    expect(screen.getByText('Capturing local files')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel operation' }))
    await waitFor(() =>
      expect(cancelBackup).toHaveBeenCalledWith(
        'source',
        'active-backup',
        'run-1',
      ),
    )
    expect(
      screen.getByRole('button', { name: 'Cancel requested' }),
    ).toBeDisabled()
    expect(screen.queryByText('Operation cancelled')).not.toBeInTheDocument()
    rerender(
      <OffsiteStatus
        health={{
          ...health,
          backup_activity: { ...activity, active: false, phase: 'cancelled' },
        }}
        onSaved={onSaved}
      />,
    )
    expect(screen.getByText('Operation cancelled')).toBeInTheDocument()
    expect(
      screen.getByRole('button', { name: 'Sync saved backup to Drive' }),
    ).toBeEnabled()
  })

  it('does not pretend cancellation succeeded if the server rejects a stale run', async () => {
    vi.mocked(cancelBackup).mockRejectedValue(
      new Error('This operation has changed. Refresh and try again.'),
    )
    render(
      <OffsiteStatus
        health={{ ...health, backup_activity: activity }}
        onSaved={() => {}}
      />,
    )
    fireEvent.click(screen.getByRole('button', { name: 'Cancel operation' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This operation has changed',
    )
    expect(
      screen.getByRole('button', { name: 'Cancel operation' }),
    ).toBeEnabled()
  })

  it('blocks repeated dispatch while queued, then permits retry after that attempt finishes', async () => {
    vi.mocked(syncBackupOffsite).mockResolvedValue({
      task_id: 'run-2',
      status: 'queued',
      message: '',
    })
    const { rerender } = render(
      <OffsiteStatus health={health} onSaved={() => {}} />,
    )
    fireEvent.click(
      screen.getByRole('button', { name: 'Sync saved backup to Drive' }),
    )
    expect(
      await screen.findByText(
        'Drive sync queued. Verification is still pending.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Sync saved backup to Drive' }),
    ).not.toBeInTheDocument()
    rerender(
      <OffsiteStatus
        health={{
          ...health,
          backup_activity: {
            ...activity,
            run_id: 'run-2',
            active: false,
            phase: 'failed',
          },
        }}
        onSaved={() => {}}
      />,
    )
    expect(
      screen.getByRole('button', { name: 'Sync saved backup to Drive' }),
    ).toBeEnabled()
  })

  it('qualifies an unconfirmed remote result after cancellation', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          backup_activity: {
            ...activity,
            active: false,
            phase: 'cancelled',
            remote_outcome_unknown: true,
          },
        }}
        onSaved={() => {}}
      />,
    )
    expect(
      screen.getByText(
        /Drive did not confirm whether the in-flight write finished/,
      ),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('Verified encrypted copy'),
    ).not.toBeInTheDocument()
  })

  it('never offers cancellation without a managed run identity or sync without a saved archive', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          latest_backup_id: null,
          backup_activity: { ...activity, run_id: null },
        }}
        onSaved={() => {}}
      />,
    )
    expect(screen.queryByRole('button')).not.toBeInTheDocument()
  })

  it('makes active work visible in the collapsed source row and blocks another capture', () => {
    render(
      <SourceCard
        source={{
          id: 'source',
          name: 'Source',
          path: '/project',
          source_type: 'project',
          project_id: 'project',
          enabled: true,
          frequency: 'daily',
          retention_days: 14,
          last_run_at: null,
          next_run_at: null,
          created_at: null,
          updated_at: null,
        }}
        health={{
          ...health,
          backup_activity: { ...activity, phase: 'encryption' },
        }}
        recentBackups={[]}
        isBackingUp={false}
        onBackupNow={() => {}}
        onSaved={() => {}}
      />,
    )
    expect(
      screen.getAllByText('Encrypting local backup').length,
    ).toBeGreaterThan(0)
    expect(screen.getByRole('button', { name: 'Backup now' })).toBeDisabled()
  })

  it('describes an opaque local phase without claiming Drive activity', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          backup_activity: { ...activity, phase: 'capture', attention: true },
        }}
        onSaved={() => {}}
      />,
    )
    expect(screen.getByText('Progress unknown')).toBeInTheDocument()
    expect(
      screen.getByText(/It is still running; you can keep waiting or cancel/),
    ).toBeInTheDocument()
    expect(
      screen.queryByText('Waiting for Drive confirmation'),
    ).not.toBeInTheDocument()
  })

  it('keeps provider metadata secondary and links to the complete source folder', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          offsite_location:
            'google-drive://owner@example.com/root-id/backup-root/source-folder/manifest-id',
        }}
        onSaved={() => {}}
      />,
    )
    expect(
      screen.getByRole('link', { name: 'Open Drive files' }),
    ).toHaveAttribute(
      'href',
      'https://drive.google.com/drive/folders/source-folder',
    )
    expect(
      screen.getByText('Drive location').closest('details'),
    ).not.toHaveAttribute('open')
  })

  it('does not discard a prior verified copy while qualifying the current attempt', () => {
    render(
      <OffsiteStatus
        health={{
          ...health,
          offsite_status: 'verified',
          offsite_error: null,
          backup_activity: { ...activity, verified_parts: 2 },
        }}
        onSaved={() => {}}
      />,
    )
    expect(screen.getByText('Verified encrypted copy')).toBeInTheDocument()
    expect(
      screen.getByText(/This attempt is not fully verified yet/),
    ).toBeInTheDocument()
  })
})
