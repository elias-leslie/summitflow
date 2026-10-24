import type {
  BackupDestinations,
  BackupHealthResponse,
  NativeHostBackupStatus,
} from '@/lib/api/backups'
import type { BtrfsScope, BtrfsSummary } from '@/lib/api/snapshots'
import { formatTimeAgo } from '@/lib/format'

/**
 * Status for the three blocks at the top of the Backups page. Each block
 * reduces its API data to one tone, a headline and a few facts, so the
 * page shows every fact once and the red/amber rules are testable.
 */

export type Tone = 'ok' | 'warn' | 'bad' | 'unknown'

export interface StatusFact {
  label: string
  value: string
  tone?: Tone
}

export interface BlockStatus {
  tone: Tone
  headline: string
  facts: StatusFact[]
}

// Used only when the API does not send its own threshold.
const DEFAULT_SNAPSHOT_STALE_HOURS = 2
// The machine backup runs once a night; a day plus the window's slack.
export const MACHINE_BACKUP_STALE_HOURS = 26
// restic sources run at least daily, and the Proxmox copy every few hours.
export const OFFSITE_COPY_STALE_HOURS = 26

const TONE_RANK: Record<Tone, number> = { ok: 0, unknown: 1, warn: 2, bad: 3 }

function worst(...tones: Tone[]): Tone {
  return tones.reduce((a, b) => (TONE_RANK[b] > TONE_RANK[a] ? b : a), 'ok')
}

function hoursSince(iso: string | null | undefined, now: Date): number | null {
  if (!iso) return null
  const time = Date.parse(iso)
  return Number.isNaN(time) ? null : (now.getTime() - time) / 3_600_000
}

function newest(values: Array<string | null | undefined>): string | null {
  let best: string | null = null
  for (const value of values) {
    if (value && (!best || Date.parse(value) > Date.parse(best))) best = value
  }
  return best
}

function ago(iso: string | null | undefined, never = 'Never'): string {
  return iso ? formatTimeAgo(iso) : never
}

// ─── Project snapshots ──────────────────────────────────────────

/**
 * Count physical snapshot points. Every project in the shared workspace
 * boundary gets its own record of the same capture, so records are grouped
 * by capture minute.
 */
export function countPoints(
  createdAt: string[],
  now: Date = new Date(),
): { total: number; lastDay: number } {
  const minutes = new Set(
    createdAt
      .filter((iso) => !Number.isNaN(Date.parse(iso)))
      .map((iso) => Math.floor(Date.parse(iso) / 60_000)),
  )
  const dayAgo = (now.getTime() - 86_400_000) / 60_000
  return {
    total: minutes.size,
    lastDay: [...minutes].filter((minute) => minute >= dayAgo).length,
  }
}

export function projectSnapshotsStatus(
  summary: BtrfsSummary | undefined,
  scopes: BtrfsScope[],
  pointTimes: string[] | undefined,
  now: Date = new Date(),
): BlockStatus {
  if (!summary)
    return { tone: 'unknown', headline: 'Status unavailable', facts: [] }
  const active = scopes.filter((scope) => scope.scope_state === 'active')
  const newestPoint =
    summary.newest_point_at ?? newest(active.map((scope) => scope.newest_at))
  const staleHours =
    summary.policy.stale_after_hours ?? DEFAULT_SNAPSHOT_STALE_HOURS
  const age = hoursSince(newestPoint, now)
  const sweep = summary.last_sweep_result ?? null
  const sweepFailed = sweep !== null && sweep !== 'ok'

  const pointTone: Tone = age === null || age > staleHours ? 'bad' : 'ok'
  const sweepTone: Tone = sweepFailed
    ? 'bad'
    : sweep === 'ok'
      ? 'ok'
      : 'unknown'
  const timerTone: Tone = summary.autosnap_timer_active ? 'ok' : 'bad'

  let headline: string
  if (age === null) headline = 'No snapshots recorded'
  else if (age > staleHours)
    headline = `Stopped: newest snapshot ${formatTimeAgo(newestPoint)}`
  else if (sweepFailed) headline = 'Last run skipped some projects'
  else if (!summary.autosnap_timer_active) headline = 'Snapshot timer is off'
  else headline = `Newest snapshot ${formatTimeAgo(newestPoint)}`

  return {
    tone: worst(pointTone, sweepFailed ? 'bad' : 'ok', timerTone),
    headline,
    facts: [
      { label: 'Newest', value: ago(newestPoint), tone: pointTone },
      {
        label: 'Last run',
        value: summary.last_sweep_at
          ? `${formatTimeAgo(summary.last_sweep_at)}${sweepFailed ? `: ${sweep}` : ''}`
          : 'Not recorded',
        tone: sweepTone,
      },
      {
        label: 'Schedule',
        value: !summary.autosnap_timer_active
          ? 'Timer off'
          : summary.autosnap_interval_minutes
            ? `Every ${summary.autosnap_interval_minutes} min`
            : 'On',
        tone: timerTone,
      },
      {
        label: 'Kept',
        value: pointTimes
          ? (() => {
              const points = countPoints(pointTimes, now)
              return `${points.total} points, ${points.lastDay} in the last day`
            })()
          : `${summary.active_scope_count} projects`,
      },
    ],
  }
}

// ─── Machine backup (btrbk to the T7) ───────────────────────────

export interface BackupSchedule {
  window?: string | null
  timezone?: string | null
}

/**
 * "02:00-06:00" → "Nightly from 02:00". Without a window the scheduler starts
 * it on its first nightly tick, so name the time the last good run started.
 */
export function scheduleLabel(
  schedule: BackupSchedule | undefined,
  lastStartedAt?: string | null,
): string {
  const start = schedule?.window?.split(',')[0]?.split('-')[0]?.trim()
  if (start) return `Nightly from ${start}`
  if (!lastStartedAt) return 'Nightly'
  const at = new Date(lastStartedAt)
  if (Number.isNaN(at.getTime())) return 'Nightly'
  try {
    const time = new Intl.DateTimeFormat('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      timeZone: schedule?.timezone ?? undefined,
    }).format(at)
    return `Nightly, last at ${time}`
  } catch {
    return 'Nightly'
  }
}

export function machineBackupStatus(
  status: NativeHostBackupStatus | undefined,
  schedule: BackupSchedule | undefined,
  now: Date = new Date(),
): BlockStatus {
  if (!status)
    return { tone: 'unknown', headline: 'Status unavailable', facts: [] }
  const good = status.last_good_result
  const lastGoodAt = good?.finished_at ?? good?.started_at ?? null
  const age = hoursSince(lastGoodAt, now)
  const latest = status.last_result
  const latestFailed =
    latest != null &&
    latest.status !== 'completed' &&
    latest.status !== 'running' &&
    (latest.finished_at ?? latest.started_at) !==
      (good?.finished_at ?? good?.started_at)

  const goodTone: Tone =
    age === null || age > MACHINE_BACKUP_STALE_HOURS ? 'bad' : 'ok'
  const restoreTone: Tone =
    status.restore_test_result === 'failed'
      ? 'bad'
      : status.restore_verified
        ? 'ok'
        : 'warn'
  const setupTone: Tone =
    !status.installed || !status.configured || !status.enabled ? 'bad' : 'ok'

  let headline: string
  if (!status.installed) headline = 'btrbk is not installed'
  else if (!status.configured) headline = 'Not configured'
  else if (!status.enabled) headline = 'Turned off'
  else if (latestFailed)
    headline = `Last run ${latest.status.replaceAll('_', ' ')}`
  else if (age === null) headline = 'No good backup yet'
  else if (age > MACHINE_BACKUP_STALE_HOURS)
    headline = `Overdue: last good ${formatTimeAgo(lastGoodAt)}`
  else if (status.restore_test_result === 'failed')
    headline = 'Restore test failed'
  else headline = `Last good ${formatTimeAgo(lastGoodAt)}`

  const restoreValue =
    status.restore_test_result === 'failed'
      ? `Failed ${ago(status.restore_tested_at, '')}`.trim()
      : status.restore_verified
        ? `Passed ${ago(status.restore_tested_at, '')}`.trim()
        : 'Not yet tested'

  return {
    tone: worst(setupTone, goodTone, latestFailed ? 'bad' : 'ok', restoreTone),
    headline,
    facts: [
      { label: 'Last good', value: ago(lastGoodAt), tone: goodTone },
      {
        label: 'Schedule',
        value: scheduleLabel(schedule, good?.started_at),
      },
      {
        label: 'Kept',
        value:
          status.points_kept != null
            ? `${status.points_kept} nightly points`
            : status.retention,
      },
      { label: 'Restore test', value: restoreValue, tone: restoreTone },
    ],
  }
}

// ─── Offsite copies (restic: T7 → Google Drive → Proxmox) ───────

export interface DestinationStatus {
  id: 't7' | 'drive' | 'proxmox'
  label: string
  lastCopyAt: string | null
  checkedAt: string | null
  tone: Tone
  note: string | null
}

export interface OffsiteStatus extends BlockStatus {
  destinations: DestinationStatus[]
  failing: Array<{ id: string; name: string }>
}

function checkTone(check: { status: string | null } | null | undefined): Tone {
  if (!check?.status) return 'unknown'
  return check.status === 'verified' ? 'ok' : 'bad'
}

function destination(
  id: DestinationStatus['id'],
  label: string,
  lastCopyAt: string | null,
  check: { checked_at: string | null; status: string | null } | null,
  now: Date,
  error: string | null = null,
): DestinationStatus {
  const age = hoursSince(lastCopyAt, now)
  const copyTone: Tone =
    age === null ? 'bad' : age > OFFSITE_COPY_STALE_HOURS ? 'bad' : 'ok'
  const ct = checkTone(check)
  return {
    id,
    label,
    lastCopyAt,
    checkedAt: check?.checked_at ?? null,
    tone: worst(copyTone, ct === 'unknown' ? 'ok' : ct),
    note:
      error ??
      (ct === 'bad' ? `Last check: ${check?.status}` : null) ??
      (age === null ? 'No copy recorded' : null),
  }
}

export function offsiteStatus(
  health: BackupHealthResponse | undefined,
  destinations: BackupDestinations | undefined,
  now: Date = new Date(),
): OffsiteStatus {
  if (!health)
    return {
      tone: 'unknown',
      headline: 'Status unavailable',
      facts: [],
      destinations: [],
      failing: [],
    }
  const enabled = health.sources.filter((source) => source.enabled)
  const failing = enabled
    .filter((source) => source.health_status === 'red')
    .map((source) => ({ id: source.source_id, name: source.source_name }))
  const driveVerified = enabled.filter(
    (source) => source.offsite_status === 'verified',
  ).length
  const pve = destinations?.proxmox ?? null

  const chain: DestinationStatus[] = [
    destination(
      't7',
      'T7',
      newest(enabled.map((source) => source.last_success_at)),
      destinations?.local_check ?? null,
      now,
    ),
    destination(
      'drive',
      'Google Drive',
      newest(enabled.map((source) => source.last_offsite_verified_at)),
      destinations?.drive_check ?? null,
      now,
    ),
  ]
  if (pve)
    chain.push(
      destination(
        'proxmox',
        'Proxmox',
        pve.last_copy_at,
        { checked_at: pve.checked_at, status: pve.check_status },
        now,
        pve.alerts[0] ?? null,
      ),
    )

  const restores = health.repositories ?? []
  const restore = restores[0]?.critical_restore
  const restoreTone: Tone = !restore
    ? 'unknown'
    : restore.status === 'verified'
      ? 'ok'
      : restore.status === 'failed'
        ? 'bad'
        : 'warn'
  const driveTone: Tone =
    enabled.length > 0 && driveVerified === enabled.length ? 'ok' : 'warn'
  const failingTone: Tone = failing.length > 0 ? 'bad' : 'ok'

  const staleDestination = chain.find((item) => item.tone === 'bad')
  let headline: string
  if (failing.length > 0)
    headline = `${failing.length} of ${enabled.length} sources failing`
  else if (staleDestination)
    headline = `${staleDestination.label} copy needs attention`
  else headline = `All ${enabled.length} sources copied`

  return {
    tone: worst(
      failingTone,
      ...chain.map((item) => item.tone),
      restoreTone === 'unknown' ? 'ok' : restoreTone,
      driveTone,
    ),
    headline,
    destinations: chain,
    failing,
    facts: [
      {
        label: 'On Drive',
        value: `${driveVerified} of ${enabled.length} latest copies verified`,
        tone: driveTone,
      },
      {
        label: 'Weekly restore test',
        value: !restore
          ? 'Not reported'
          : restore.status === 'verified'
            ? `Passed ${ago(restore.last_success_at, '')}`.trim()
            : restore.status === 'untested'
              ? 'Not yet tested'
              : `${restore.status[0].toUpperCase()}${restore.status.slice(1)}`,
        tone: restoreTone,
      },
    ],
  }
}

export const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-emerald-300',
  warn: 'text-amber-300',
  bad: 'text-rose-300',
  unknown: 'text-slate-400',
}

export const TONE_BORDER: Record<Tone, string> = {
  ok: 'border-l-emerald-500',
  warn: 'border-l-amber-500',
  bad: 'border-l-rose-500',
  unknown: 'border-l-slate-600',
}

export const TONE_LABEL: Record<Tone, string> = {
  ok: 'OK',
  warn: 'Check',
  bad: 'Needs attention',
  unknown: 'Unknown',
}
