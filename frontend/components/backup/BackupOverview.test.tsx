import { render, screen } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import { type BackupOverview, parseBackupOverview } from '@/lib/api/backups'
import { DriveCard } from './DriveCard'
import { HealthBanner } from './HealthBanner'
import { LocalPointsCard } from './LocalPointsCard'
import { OldBackups } from './OldBackups'

const NOW = new Date('2026-10-26T12:00:00Z')
const ago = (hours: number) =>
  new Date(NOW.getTime() - hours * 3_600_000).toISOString()

beforeAll(() => {
  vi.useFakeTimers()
  vi.setSystemTime(NOW)
})
afterAll(() => {
  vi.useRealTimers()
})

function overview(patch: Record<string, unknown> = {}): BackupOverview {
  return parseBackupOverview({
    generated_at: NOW.toISOString(),
    ok: true,
    problems: [],
    local: {
      enabled: true,
      schedule: 'every 4 hours',
      keeps: '7 days',
      last_run: {
        status: 'completed',
        started_at: ago(2.1),
        finished_at: ago(2),
        error: null,
      },
      last_good_at: ago(2),
      next_run_at: null,
      target: {
        path: '/mnt/t7',
        free_bytes: 600 * 2 ** 30,
        used_bytes: 400 * 2 ** 30,
        total_bytes: 1000 * 2 ** 30,
      },
      points: { workspaces: 8, var_log: 7 },
    },
    offsite: {
      schedule: 'daily',
      repository: 'rclone:gdrive:backups',
      last_success_at: ago(14),
      running: null,
      jobs: {
        workspaces: { status: 'ok', time: ago(14), bytes: 2 ** 30 },
        'pve-guest-100': { status: 'ok', time: ago(20), bytes: 5 },
        'disk-b': { status: 'ok', time: ago(15), bytes: 5 },
      },
      check: { status: 'ok', sample: '500M', last_ok_at: ago(14), failures: 0 },
      spot_restore: { at: ago(80), status: 'ok' },
      maintenance: { ran_at: ago(14), pruned_at: ago(100) },
      runs: [],
      ...((patch.offsite as object) ?? {}),
    },
    legacy: {
      local_repository: { path: '/mnt/t7/restic', bytes: 2 ** 30 },
      drive_snapshots: { count: 143, ages_out_after_days: 30 },
      retired_sources: 12,
    },
    ...patch,
  })
}

describe('HealthBanner', () => {
  it('is calm when nothing is missing', () => {
    render(<HealthBanner overview={overview()} />)
    expect(screen.getByText('All backups current')).toBeInTheDocument()
  })

  it('does not claim everything is current before the first Drive copy', () => {
    render(
      <HealthBanner
        overview={overview({
          offsite: { last_success_at: null, jobs: {}, check: null },
        })}
      />,
    )
    expect(screen.queryByText('All backups current')).toBeNull()
    expect(screen.getByText('Nothing is missing')).toBeInTheDocument()
  })

  it('lists the problems it is given', () => {
    render(
      <HealthBanner
        overview={overview({
          ok: false,
          problems: [
            {
              key: 'offsite-missing',
              title: 'No recent Google Drive backup',
              message: '3 days ago',
            },
          ],
        })}
      />,
    )
    expect(screen.getByText('A backup needs attention')).toBeInTheDocument()
    expect(
      screen.getByText('No recent Google Drive backup'),
    ).toBeInTheDocument()
  })
})

describe('LocalPointsCard', () => {
  it('shows the schedule, newest point, free space and points per folder', () => {
    render(<LocalPointsCard overview={overview()} />)
    expect(screen.getByText('Every 4 hours')).toBeInTheDocument()
    expect(screen.getByText('Newest point 2h ago')).toBeInTheDocument()
    expect(screen.getByText('600.0 GB free')).toBeInTheDocument()
    expect(screen.getByText('Projects')).toBeInTheDocument()
    expect(screen.getByText('Logs')).toBeInTheDocument()
    expect(screen.getByText('Not available')).toBeInTheDocument()
  })
})

describe('DriveCard', () => {
  it('lists each job, groups the rest, and reports check, test restore and cleanup', () => {
    render(<DriveCard overview={overview()} />)
    expect(screen.getByText('Last good copy 14h ago')).toBeInTheDocument()
    expect(screen.getByText('Passed 14h ago, 500 MB read')).toBeInTheDocument()
    expect(screen.getByText('Passed 3d ago')).toBeInTheDocument()
    expect(screen.getByText('Proxmox and other disks')).toBeInTheDocument()
    expect(screen.getByText('rclone:gdrive:backups')).toBeInTheDocument()
    expect(screen.getAllByText('Not copied yet')).toHaveLength(4)
  })

  it('says the checks run weekly and marks a failed daily run as failed', () => {
    render(
      <DriveCard
        overview={overview({
          offsite: {
            runs: [
              {
                status: 'failed',
                started_at: ago(80),
                error: 'restic snapshots returned invalid JSON',
              },
              { status: 'ok', started_at: ago(14) },
            ],
          },
        })}
      />,
    )
    expect(screen.getByText('Weekly data check')).toBeInTheDocument()
    expect(screen.getByText('Weekly test restore')).toBeInTheDocument()
    expect(screen.getByText('Weekly cleanup')).toBeInTheDocument()
    expect(screen.getByText('Good')).toBeInTheDocument()
    expect(
      screen.getByText('Failed: restic snapshots returned invalid JSON'),
    ).toBeInTheDocument()
  })

  it('stays quiet before the first run', () => {
    render(
      <DriveCard
        overview={overview({
          offsite: {
            last_success_at: null,
            jobs: {},
            check: null,
            spot_restore: null,
            maintenance: null,
            repository: null,
          },
        })}
      />,
    )
    expect(screen.getByText('First copy not made yet')).toBeInTheDocument()
    expect(screen.getByText('Waiting')).toBeInTheDocument()
  })

  it('calls a read-back that ran out of time out of time, not failed', () => {
    render(
      <DriveCard
        overview={overview({
          offsite: {
            check: {
              status: 'partial',
              sample: '500M',
              checked_at: ago(20),
              failures: 0,
            },
            spot_restore: { at: ago(20), status: 'partial' },
          },
        })}
      />,
    )
    expect(
      screen.getByText('Out of time 20h ago; reads a new sample next week'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('Out of time 20h ago; tries again next week'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/Failed/)).not.toBeInTheDocument()
  })

  it('says when a copy is running', () => {
    render(
      <DriveCard
        overview={overview({ offsite: { running: { started_at: ago(0.5) } } })}
      />,
    )
    expect(screen.getByText('Copying now, started 30m ago')).toBeInTheDocument()
  })
})

describe('OldBackups', () => {
  it('names what is left and offers nothing to click except the disclosure', () => {
    render(<OldBackups legacy={overview().legacy} />)
    expect(screen.getAllByRole('button')).toHaveLength(1)
    expect(screen.getByText(/143 copies left/)).toBeInTheDocument()
    expect(
      screen.getByText(/removed on their own after 30 days/),
    ).toBeInTheDocument()
    expect(screen.getByText(/so you can delete it/)).toBeInTheDocument()
  })

  it('says the old T7 repository is not found instead of offering to delete it', () => {
    const { legacy } = overview()
    render(
      <OldBackups
        legacy={{
          ...legacy,
          local_repository: {
            path: '/mnt/t7/restic',
            bytes: null,
            missing: true,
          },
        }}
      />,
    )
    expect(screen.getByText('Not found at /mnt/t7/restic.')).toBeInTheDocument()
    expect(screen.queryByText(/delete it/)).toBeNull()
  })

  it('says the old Drive copies are kept while the age-out is paused', () => {
    const legacy = parseBackupOverview({
      ...overview(),
      legacy: {
        local_repository: { path: '/mnt/t7/restic', bytes: 2 ** 30 },
        drive_snapshots: {
          count: 143,
          ages_out_after_days: 36500,
          paused: true,
        },
        retired_sources: 0,
      },
    }).legacy
    render(<OldBackups legacy={legacy} />)
    expect(screen.getByText('Old backups')).toBeInTheDocument()
    expect(screen.getByText(/kept: the age-out is paused/)).toBeInTheDocument()
    expect(screen.queryByText(/36500/)).toBeNull()
  })
})
