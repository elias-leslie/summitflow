import type {
  BackupHealthItem,
  BackupHealthResponse,
  NativeHostBackupStatus,
} from '@/lib/api/backups'
import type { BtrfsSummary } from '@/lib/api/snapshots'

// Shared by the status-logic and status-card tests. Tests pin the clock to `now`.
export const now = new Date('2026-10-24T14:00:00Z')

export const hoursAgo = (hours: number) =>
  new Date(now.getTime() - hours * 3_600_000).toISOString()

export const summary = (
  overrides: Partial<BtrfsSummary> = {},
): BtrfsSummary => ({
  total_snapshots: 10,
  total_usage_bytes: null,
  by_source: {},
  by_scope_type: {},
  scope_count: 3,
  active_snapshot_count: 10,
  archived_snapshot_count: 0,
  active_scope_count: 3,
  archived_scope_count: 0,
  policy: {
    interval_minutes: 15,
    baseline_stale_minutes: 15,
    recent_hours: 6,
    hourly_hours: 24,
    daily_days: 3,
    archived_keep_days: 14,
    pressure_keep_points: 3,
    manual_keep_per_scope: 20,
    max_deletes_per_run: 15,
    delete_batch: 5,
    stale_after_hours: 2,
  },
  autosnap_timer_active: true,
  newest_point_at: hoursAgo(0.25),
  last_sweep_at: hoursAgo(0.25),
  last_sweep_result: 'ok',
  ...overrides,
})

export const host = (
  overrides: Partial<NativeHostBackupStatus> = {},
): NativeHostBackupStatus => ({
  engine: 'btrbk',
  enabled: true,
  installed: true,
  configured: true,
  ready: true,
  retention: '7 daily destination points',
  restore_verified: false,
  restore_tested_at: null,
  restore_test_result: null,
  points_kept: 7,
  last_result: {
    status: 'completed',
    started_at: hoursAgo(8),
    finished_at: hoursAgo(7.9),
  },
  last_good_result: {
    status: 'completed',
    started_at: hoursAgo(8),
    finished_at: hoursAgo(7.9),
  },
  ...overrides,
})

export const item = (
  overrides: Partial<BackupHealthItem>,
): BackupHealthItem => ({
  source_id: 'agent-hub',
  source_name: 'Agent Hub',
  source_type: 'project',
  enabled: true,
  health_status: 'green',
  last_success_at: hoursAgo(1),
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
  latest_backup_id: null,
  offsite_status: 'verified',
  last_offsite_verified_at: hoursAgo(1),
  offsite_location: null,
  offsite_checksum: null,
  offsite_error: null,
  last_isolated_restore_at: null,
  last_isolated_restore_ok: null,
  ...overrides,
})

export const health = (sources: BackupHealthItem[]): BackupHealthResponse => ({
  sources,
  pending_upload_count: 0,
  repositories: [
    {
      backend_id: 'restic',
      backend_name: 'Restic',
      critical_restore: {
        status: 'verified',
        last_success_at: hoursAgo(30),
        latest_attempt: null,
        required_source_ids: [],
        verified_source_ids: [],
        missing_source_ids: [],
      },
    },
  ],
})

export const checked = { checked_at: hoursAgo(5), status: 'verified' }
