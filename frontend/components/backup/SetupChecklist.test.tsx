import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type {
  BackupHealthItem,
  BackupSource,
  StorageStatus,
} from '@/lib/api/backups'
import { SetupChecklist } from './SetupChecklist'

vi.mock('@/lib/api/backups', () => ({
  createBackupSource: vi.fn(),
  createSourceBackup: vi.fn(),
  updateBackupSource: vi.fn(),
}))

describe('SetupChecklist', () => {
  it('starts collapsed and shows a progress summary line', () => {
    render(
      <SetupChecklist
        storageStatus={undefined}
        sources={[]}
        healthItems={[]}
        isLoading={false}
        onSourceChanged={() => {}}
        onBackupTriggered={() => {}}
      />,
    )

    expect(
      screen.getByText('0 of 6 complete. 6 steps still need attention.'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Backup storage')).not.toBeInTheDocument()
  })

  it('reveals setup steps after expanding the checklist', () => {
    render(
      <SetupChecklist
        storageStatus={undefined}
        sources={[]}
        healthItems={[]}
        isLoading={false}
        onSourceChanged={() => {}}
        onBackupTriggered={() => {}}
      />,
    )

    fireEvent.click(
      screen.getByRole('button', { name: /set up backup protection/i }),
    )

    expect(screen.getByText('Backup storage')).toBeInTheDocument()
    expect(screen.getByText('Backup sources')).toBeInTheDocument()
  })

  it('does not call protection complete without a saved key and verified Drive copy', () => {
    const source = {
      id: 'infrastructure',
      name: 'System Backup',
      path: '/',
      source_type: 'infrastructure',
      project_id: null,
      enabled: true,
      frequency: 'daily',
      retention_days: 7,
      last_run_at: null,
      next_run_at: null,
      created_at: null,
      updated_at: null,
    } satisfies BackupSource
    const health = {
      source_id: source.id,
      source_name: source.name,
      source_type: source.source_type,
      enabled: true,
      health_status: 'yellow',
      last_success_at: '2026-09-21T12:00:00Z',
      next_run_at: null,
      failure_count_7d: 0,
      pending_upload_count: 0,
      last_restore_tested_at: null,
      last_restore_test_ok: null,
      latest_backup_age_hours: 1,
      latest_restore_test_age_hours: null,
      restore_test_backup_id: null,
      coverage_complete: true,
      pitr_supported: false,
      restore_confidence: 'verified',
      last_drill_at: '2026-09-21T12:10:00Z',
      last_drill_ok: true,
      last_drill_backup_id: 'backup-current',
      latest_backup_id: 'backup-current',
      offsite_status: 'pending',
      last_offsite_verified_at: null,
      offsite_location: null,
      offsite_checksum: null,
      offsite_error: null,
      last_isolated_restore_at: null,
      last_isolated_restore_ok: null,
    } satisfies BackupHealthItem
    const storage = {
      configured: true,
      backend_count: 1,
      default_backend_id: 'local',
      default_backend_name: 'Backup disk',
    } satisfies StorageStatus
    const props = {
      storageStatus: storage,
      sources: [source],
      healthItems: [health],
      encryptionReady: false,
      isLoading: false,
      onSourceChanged: () => {},
      onBackupTriggered: () => {},
    }
    const { rerender } = render(<SetupChecklist {...props} />)
    expect(
      screen.queryByText('Backup protection fully configured'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText('4 of 6 complete. 2 steps still need attention.'),
    ).toBeInTheDocument()

    rerender(
      <SetupChecklist
        {...props}
        encryptionReady
        healthItems={[{ ...health, offsite_status: 'verified' }]}
      />,
    )
    expect(
      screen.getByText('Backup protection checks passed'),
    ).toBeInTheDocument()

    rerender(
      <SetupChecklist
        {...props}
        encryptionReady
        healthItems={[
          {
            ...health,
            offsite_status: 'verified',
            last_drill_backup_id: 'older-backup',
          },
        ]}
      />,
    )
    expect(
      screen.queryByText('Backup protection checks passed'),
    ).not.toBeInTheDocument()
    expect(
      screen.getByText('5 of 6 complete. 1 step still needs attention.'),
    ).toBeInTheDocument()
    rerender(
      <SetupChecklist
        {...props}
        encryptionReady
        healthItems={[
          { ...health, offsite_status: 'verified', coverage_complete: false },
        ]}
      />,
    )
    expect(
      screen.queryByText('Backup protection checks passed'),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /backup setup:/i }))
    expect(
      screen.getByText(
        'Required recovery state is missing from the latest system backup.',
      ),
    ).toBeInTheDocument()
  })
})
