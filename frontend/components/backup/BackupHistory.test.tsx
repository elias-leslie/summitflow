import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Backup } from '@/lib/api/backups'
import { BackupHistory, previewBackups } from './BackupHistory'

const run = (id: string, source_id: string, status: Backup['status']) =>
  ({
    id,
    project_id: 'summitflow',
    name: id,
    backup_type: 'scheduled',
    status,
    size_bytes: null,
    db_size_bytes: null,
    files_size_bytes: null,
    location: null,
    note: null,
    created_at: '2026-10-24T12:00:00Z',
    started_at: null,
    completed_at: null,
    error_message: null,
    verified: null,
    verified_at: null,
    checksum: null,
    total_files: null,
    verification_json: null,
    source_id,
  }) satisfies Backup

// Newest first, as the API returns them.
const runs = [
  ...Array.from({ length: 12 }, (_, i) => run(`ok-${i}`, `s${i}`, 'completed')),
  run('fixed-old-failure', 's0', 'failed'),
  run('still-failing', 'chrome', 'failed'),
]

describe('previewBackups', () => {
  it('pins sources whose latest run failed, then fills with the newest runs', () => {
    const shown = previewBackups(runs)
    expect(shown).toHaveLength(10)
    expect(shown[0].id).toBe('still-failing')
    expect(shown.map((b) => b.id)).not.toContain('fixed-old-failure')
    expect(shown[1].id).toBe('ok-0')
  })
})

describe('BackupHistory', () => {
  it('shows ten runs until "Show all" is pressed', () => {
    render(
      <BackupHistory
        backups={runs}
        sources={[]}
        isLoading={false}
        error={null}
        onRetry={() => {}}
        statusFilter=""
        onStatusFilterChange={() => {}}
      />,
    )
    const phoneList = screen.getByRole('list', { name: 'Backup runs' })
    expect(within(phoneList).getAllByRole('listitem')).toHaveLength(10)
    fireEvent.click(
      screen.getByRole('button', { name: 'Show all 14 recent runs' }),
    )
    expect(within(phoneList).getAllByRole('listitem')).toHaveLength(14)
    expect(
      screen.getByRole('button', { name: 'Show fewer' }),
    ).toBeInTheDocument()
  })
})
