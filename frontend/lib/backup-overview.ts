import type { DriveBackups, DriveJob, LocalBackups } from '@/lib/api/backups'
import { formatBytes, formatTimeAgo } from '@/lib/format'

/** What each name in the overview means to the owner. Unknown names show as sent. */
const POINT_LABELS: Record<string, string> = {
  workspaces: 'Projects',
  home: 'Home folders',
  root: 'System',
  docker: 'Docker',
  models: 'Models',
  var_log: 'Logs',
}

const DRIVE_LABELS: Array<[string, string]> = [
  ['workspaces', 'Projects'],
  ['home', 'Home folders'],
  ['root', 'System settings'],
  ['postgres', 'PostgreSQL'],
  ['redis', 'Redis'],
]

const OK_WORDS = new Set(['ok', 'completed', 'success', 'passed', 'verified'])

export function isOk(status: string | null | undefined): boolean {
  return OK_WORDS.has((status ?? '').toLowerCase())
}

export function isRunning(status: string | null | undefined): boolean {
  return (status ?? '').toLowerCase() === 'running'
}

/** "3h ago" for the past, "in 2h" for the future, otherwise the fallback. */
export function relativeTime(
  iso: string | null | undefined,
  fallback: string,
): string {
  if (!iso || Number.isNaN(Date.parse(iso))) return fallback
  const ms = Date.parse(iso) - Date.now()
  if (ms <= 0) return formatTimeAgo(iso, fallback)
  const minutes = Math.round(ms / 60_000)
  if (minutes < 1) return 'in under a minute'
  if (minutes < 60) return `in ${minutes}m`
  const hours = Math.floor(minutes / 60)
  return minutes % 60 === 0 || hours >= 10
    ? `in ${hours}h`
    : `in ${hours}h ${minutes % 60}m`
}

export function pointRows(
  points: LocalBackups['points'],
): Array<{ name: string; label: string; count: number }> {
  return Object.entries(points ?? {})
    .map(([name, count]) => ({
      name,
      label: POINT_LABELS[name] ?? name.replaceAll('_', ' '),
      count,
    }))
    .sort((a, b) => a.label.localeCompare(b.label))
}

export function spaceUsage(target: NonNullable<LocalBackups['target']>): {
  usedPercent: number
  free: string
  used: string
  total: string
} {
  const total = target.total_bytes
  return {
    usedPercent:
      total > 0
        ? Math.min(
            100,
            Math.max(0, Math.round((target.used_bytes / total) * 100)),
          )
        : 0,
    free: formatBytes(target.free_bytes),
    used: formatBytes(target.used_bytes),
    total: formatBytes(total),
  }
}

export interface DriveRow {
  key: string
  label: string
  /** True when Google Drive holds a good copy of this job. */
  has: boolean
  failed: boolean
  when: string | null
  size: string | null
  note: string | null
}

function jobRow(
  key: string,
  label: string,
  job: DriveJob | undefined,
): DriveRow {
  const failed = !!job && !isOk(job.status) && job.status !== 'offline'
  return {
    key,
    label,
    has: !!job && !!job.time,
    failed,
    when: job?.time ?? null,
    size: job?.bytes ? formatBytes(job.bytes) : null,
    note: failed ? (job?.error ?? 'Did not back up') : null,
  }
}

/** The named jobs first, then Proxmox guests and drives outside the machine as one row. */
export function driveRows(jobs: DriveBackups['jobs']): DriveRow[] {
  const named = new Set(DRIVE_LABELS.map(([key]) => key))
  const rows = DRIVE_LABELS.map(([key, label]) => jobRow(key, label, jobs[key]))
  const others = Object.entries(jobs).filter(([key]) => !named.has(key))
  if (others.length > 0) {
    const times = others
      .map(([, job]) => job.time)
      .filter((time): time is string => !!time)
      .sort()
    const failed = others.filter(
      ([, job]) => !isOk(job.status) && job.status !== 'offline',
    )
    rows.push({
      key: 'other',
      label: 'Proxmox and other disks',
      has: times.length > 0,
      failed: failed.length > 0,
      when: times[0] ?? null,
      size: null,
      note:
        failed.length > 0
          ? `${failed.map(([key]) => key).join(', ')} did not back up`
          : `${others.length} ${others.length === 1 ? 'source' : 'sources'}; the time is the oldest copy`,
    })
  }
  return rows
}
