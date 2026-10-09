import { afterEach, describe, expect, it, vi } from 'vitest'
import { parseBackupHealth } from './backups-health'
import {
  type BackupHealthItem,
  type BackupRepositoryHealthItem,
  fetchBackupHealth,
} from './backups-infra'

const source: BackupHealthItem = {
  source_id: 'configuration',
  source_name: 'Configuration',
  source_type: 'config',
  enabled: true,
  health_status: 'green',
  last_success_at: '2026-10-08T10:00:00Z',
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
  latest_backup_id: 'point',
  offsite_status: 'verified',
  last_offsite_verified_at: '2026-10-08T10:00:00Z',
  offsite_location: null,
  offsite_checksum: null,
  offsite_error: null,
  last_isolated_restore_at: null,
  last_isolated_restore_ok: null,
}

const repository: BackupRepositoryHealthItem = {
  backend_id: 'drive',
  backend_name: 'Offsite repository',
  critical_restore: {
    status: 'failed',
    last_success_at: '2026-10-01T10:00:00Z',
    latest_attempt: {
      status: 'failed',
      attempted_at: '2026-10-08T10:00:00Z',
      completed_at: '2026-10-08T10:02:00Z',
      failed_source_id: 'configuration',
      reason: 'mapped-links-unresolved',
      cached: true,
    },
    required_source_ids: ['configuration', 'infrastructure'],
    verified_source_ids: ['configuration', 'infrastructure'],
    missing_source_ids: [],
  },
}
const health = {
  sources: [source],
  pending_upload_count: 0,
  repositories: [repository],
}

afterEach(() => vi.restoreAllMocks())

describe('backup health runtime schema', () => {
  it('retains the previous pass and current failed attempt independently', () => {
    expect(parseBackupHealth(health)).toEqual(health)
  })

  it('accepts older servers without inventing a weekly result', () => {
    const older = { sources: [], pending_upload_count: 0 }
    expect(parseBackupHealth(older).repositories).toBeUndefined()
    expect(
      parseBackupHealth({ ...older, repositories: [] }).repositories,
    ).toEqual([])
  })

  it.each([
    null,
    { ...health, sources: [{}] },
    { ...health, pending_upload_count: '0' },
    { ...health, sources: [{ ...source, offsite_status: 'passed' }] },
    { ...health, repositories: null },
    {
      ...health,
      repositories: [
        {
          ...repository,
          critical_restore: {
            ...repository.critical_restore,
            status: 'success',
          },
        },
      ],
    },
    {
      ...health,
      repositories: [
        {
          ...repository,
          critical_restore: {
            ...repository.critical_restore,
            last_success_at: 'yesterday',
          },
        },
      ],
    },
    {
      ...health,
      repositories: [
        {
          ...repository,
          critical_restore: {
            ...repository.critical_restore,
            verified_source_ids: [42],
          },
        },
      ],
    },
    {
      ...health,
      repositories: [
        {
          ...repository,
          critical_restore: {
            ...repository.critical_restore,
            latest_attempt: {
              ...repository.critical_restore.latest_attempt,
              cached: 'false',
            },
          },
        },
      ],
    },
    {
      ...health,
      repositories: [
        {
          ...repository,
          critical_restore: {
            ...repository.critical_restore,
            latest_attempt: {
              ...repository.critical_restore.latest_attempt,
              reason: 'raw-error',
            },
          },
        },
      ],
    },
  ])(
    'rejects malformed external health without a success fallback',
    (value) => {
      expect(() => parseBackupHealth(value)).toThrow(
        'Backup health response is incompatible',
      )
    },
  )

  it('validates the actual fetch boundary', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(
      new Response(JSON.stringify({ ...health, repositories: [{}] }), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    await expect(fetchBackupHealth()).rejects.toThrow(
      'Backup health response is incompatible',
    )
  })
})
