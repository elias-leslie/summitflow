import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import {
  countPoints,
  machineBackupStatus,
  offsiteStatus,
  projectSnapshotsStatus,
  scheduleLabel,
} from './backup-status'
import {
  checked,
  health,
  host,
  hoursAgo,
  item,
  now,
  summary,
} from './backup-status.fixtures'

// Relative times ("15m ago") read the clock, so pin it to `now`.
beforeAll(() => {
  vi.useFakeTimers()
  vi.setSystemTime(now)
})
afterAll(() => {
  vi.useRealTimers()
})

describe('projectSnapshotsStatus', () => {
  it('is ok when the newest point is fresh and the last run was clean', () => {
    const status = projectSnapshotsStatus(summary(), [], undefined, now)
    expect(status.tone).toBe('ok')
    expect(status.headline).toBe('Newest snapshot 15m ago')
  })

  it("shows the timer's own interval, not the capture policy's", () => {
    const schedule = (interval: number | null) =>
      projectSnapshotsStatus(
        summary({ autosnap_interval_minutes: interval }),
        [],
        undefined,
        now,
      ).facts.find((fact) => fact.label === 'Schedule')?.value
    expect(schedule(30)).toBe('Every 30 min')
    expect(schedule(null)).toBe('On')
  })

  it('turns red once the newest point is older than the threshold, even with the timer active', () => {
    const status = projectSnapshotsStatus(
      summary({ newest_point_at: hoursAgo(4 * 24) }),
      [],
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
    expect(status.headline).toMatch(/^Stopped: newest snapshot/)
    expect(status.facts[0]).toMatchObject({ label: 'Newest', tone: 'bad' })
  })

  it('turns red when the last run reports failures', () => {
    const status = projectSnapshotsStatus(
      summary({ last_sweep_result: '1 of 29 projects failed: neri: denied' }),
      [],
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
    expect(status.facts[1].value).toContain('neri: denied')
  })

  it('falls back to the newest active scope point before the sweep state exists', () => {
    const status = projectSnapshotsStatus(
      summary({ newest_point_at: null, last_sweep_result: null }),
      [
        {
          project_id: 'a',
          scope_type: 'project',
          scope_name: 'a',
          scope_state: 'active',
          snapshot_count: 1,
          total_bytes: null,
          newest_at: hoursAgo(5),
          oldest_at: null,
        },
      ],
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
  })

  it('is red with no points at all', () => {
    const status = projectSnapshotsStatus(
      summary({ newest_point_at: null }),
      [],
      undefined,
      now,
    )
    expect(status).toMatchObject({
      tone: 'bad',
      headline: 'No snapshots recorded',
    })
  })
})

describe('countPoints', () => {
  it('groups per-project records of one capture into one point', () => {
    const capture = hoursAgo(1)
    expect(
      countPoints([capture, capture, hoursAgo(30), hoursAgo(30)], now),
    ).toEqual({ total: 2, lastDay: 1 })
  })
})

describe('machineBackupStatus', () => {
  it('says "Not yet tested" and stays amber until a restore test passes', () => {
    const status = machineBackupStatus(host(), { window: '02:00-06:00' }, now)
    expect(status.tone).toBe('warn')
    expect(status.facts).toContainEqual({
      label: 'Restore test',
      value: 'Not yet tested',
      tone: 'warn',
    })
  })

  it('is ok after a passed restore test', () => {
    const status = machineBackupStatus(
      host({
        restore_verified: true,
        restore_test_result: 'verified',
        restore_tested_at: hoursAgo(48),
      }),
      { window: '02:00-06:00' },
      now,
    )
    expect(status.tone).toBe('ok')
    expect(status.headline).toBe('Last good 7h ago')
  })

  it('turns red when the last good backup is overdue', () => {
    const old = { status: 'completed', finished_at: hoursAgo(50) }
    const status = machineBackupStatus(
      host({ last_result: old, last_good_result: old, restore_verified: true }),
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
    expect(status.headline).toMatch(/^Overdue/)
  })

  it('turns red when the latest run failed after the last good one', () => {
    const status = machineBackupStatus(
      host({
        last_result: { status: 'failed', started_at: hoursAgo(1) },
        restore_verified: true,
      }),
      undefined,
      now,
    )
    expect(status).toMatchObject({ tone: 'bad', headline: 'Last run failed' })
  })

  it('turns red on a failed restore test', () => {
    const status = machineBackupStatus(
      host({ restore_test_result: 'failed', restore_tested_at: hoursAgo(2) }),
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
  })

  it('reports points kept from the T7', () => {
    const status = machineBackupStatus(host(), undefined, now)
    expect(status.facts).toContainEqual({
      label: 'Kept',
      value: '7 nightly points',
    })
  })
})

describe('scheduleLabel', () => {
  it('names the start of the nightly window', () => {
    expect(scheduleLabel({ window: '02:00-06:00' })).toBe('Nightly from 02:00')
    expect(scheduleLabel(undefined)).toBe('Nightly')
  })

  it('names the last start in the schedule timezone when no window is set', () => {
    expect(
      scheduleLabel(
        { window: null, timezone: 'America/New_York' },
        '2026-10-24T06:30:00Z',
      ),
    ).toBe('Nightly, last at 02:30')
  })
})

describe('offsiteStatus', () => {
  it('lists T7, Drive and Proxmox in order with their last copy and check', () => {
    const status = offsiteStatus(
      health([item({})]),
      {
        schedule_window: null,
        schedule_timezone: 'UTC',
        local_check: checked,
        drive_check: checked,
        check_alerts: [],
        proxmox: {
          last_copy_at: hoursAgo(2),
          last_attempt_at: hoursAgo(2),
          error: null,
          checked_at: hoursAgo(100),
          check_status: 'verified',
          alerts: [],
        },
      },
      now,
    )
    expect(status.tone).toBe('ok')
    expect(status.destinations.map((d) => [d.label, d.tone])).toEqual([
      ['T7', 'ok'],
      ['Google Drive', 'ok'],
      ['Proxmox', 'ok'],
    ])
  })

  it('names failing sources and turns red', () => {
    const status = offsiteStatus(
      health([
        item({}),
        item({
          source_id: 'neri-evidence',
          source_name: 'Neri evidence',
          health_status: 'red',
        }),
        item({ source_id: 'off', enabled: false, health_status: 'red' }),
      ]),
      undefined,
      now,
    )
    expect(status.tone).toBe('bad')
    expect(status.headline).toBe('1 of 2 sources failing')
    expect(status.failing).toEqual([
      { id: 'neri-evidence', name: 'Neri evidence' },
    ])
  })

  it('flags a stale Proxmox copy', () => {
    const status = offsiteStatus(
      health([item({})]),
      {
        schedule_window: null,
        schedule_timezone: 'UTC',
        local_check: checked,
        drive_check: checked,
        check_alerts: [],
        proxmox: {
          last_copy_at: hoursAgo(60),
          last_attempt_at: hoursAgo(1),
          error: 'exit 1',
          checked_at: null,
          check_status: null,
          alerts: ['The PVE backup copy last succeeded 60h ago'],
        },
      },
      now,
    )
    expect(status.tone).toBe('bad')
    expect(status.headline).toBe('Proxmox copy needs attention')
    expect(status.destinations[2].note).toContain('60h ago')
  })

  it('treats a failed repository check as red', () => {
    const status = offsiteStatus(
      health([item({})]),
      {
        schedule_window: null,
        schedule_timezone: 'UTC',
        local_check: checked,
        drive_check: { checked_at: hoursAgo(1), status: 'failed' },
        check_alerts: [],
        proxmox: null,
      },
      now,
    )
    expect(status.destinations[1]).toMatchObject({
      tone: 'bad',
      note: 'Last check: failed',
    })
  })
})
