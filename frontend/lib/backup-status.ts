import type { BtrfsScope, BtrfsSummary } from '@/lib/api/snapshots'
import { formatTimeAgo } from '@/lib/format'

/** Tone, headline and facts for a status block; the project snapshots block uses it. */

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
