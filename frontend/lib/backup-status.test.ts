import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { countPoints, projectSnapshotsStatus } from './backup-status'
import { hoursAgo, now, summary } from './backup-status.fixtures'

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
