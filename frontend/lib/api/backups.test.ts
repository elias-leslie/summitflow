import { describe, expect, it } from 'vitest'
import { parseBackupOverview } from './backups'

const firstRun = {
  generated_at: '2026-10-26T12:47:15+00:00',
  ok: true,
  problems: [],
  local: {
    enabled: true,
    schedule: 'every 4 hours',
    keeps: '7 days',
    last_run: {
      status: 'completed',
      started_at: '2026-10-26T06:30:00+00:00',
      finished_at: '2026-10-26T06:33:14+00:00',
      error: null,
    },
    last_good_at: '2026-10-26T06:33:14+00:00',
    next_run_at: null,
    target: { path: '/t7', free_bytes: 6, used_bytes: 4, total_bytes: 10 },
    points: { workspaces: 8, var_log: 8 },
  },
  offsite: {
    schedule: 'daily',
    repository: null,
    last_success_at: null,
    jobs: {},
    check: null,
    spot_restore: null,
    maintenance: null,
    runs: [],
  },
  legacy: {
    local_repository: { path: null, bytes: null },
    drive_snapshots: { count: null, ages_out_after_days: 30 },
    retired_sources: 12,
  },
}

describe('parseBackupOverview', () => {
  it('keeps nulls before the first Drive run instead of inventing values', () => {
    const overview = parseBackupOverview(firstRun)
    expect(overview.offsite.last_success_at).toBeNull()
    expect(overview.offsite.check).toBeNull()
    expect(overview.offsite.running).toBeNull()
    expect(overview.local.next_run_at).toBeNull()
    expect(overview.local.points).toEqual({ workspaces: 8, var_log: 8 })
    expect(overview.legacy.drive_snapshots.count).toBeNull()
  })

  it('reads the Drive check slices whether coverage is a map or missing', () => {
    const drive = {
      ...firstRun.offsite,
      check: {
        status: 'ok',
        bucket: '3/30',
        coverage: { '1': 'a', '2': 'b', '3': 'c' },
        failures: 0,
      },
    }
    const overview = parseBackupOverview({ ...firstRun, offsite: drive })
    expect(overview.offsite.check?.covered).toBe(3)
    expect(overview.offsite.check?.bucket).toBe('3/30')
  })

  it('rejects a body that is not an overview', () => {
    expect(() => parseBackupOverview({ detail: 'nope' })).toThrow()
  })
})
