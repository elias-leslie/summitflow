import type { BtrfsSummary } from '@/lib/api/snapshots'

// Shared by the status-logic tests. Tests pin the clock to `now`.
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
  autosnap_interval_minutes: 30,
  newest_point_at: hoursAgo(0.25),
  last_sweep_at: hoursAgo(0.25),
  last_sweep_result: 'ok',
  ...overrides,
})
