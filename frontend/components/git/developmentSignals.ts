import type {
  DevelopmentEvidence,
  DevelopmentProjection,
  RepoStatus,
} from '@/lib/api/git'
import { formatTimeAgo } from '@/lib/format'

/** ok: done for HEAD · info: expected in-flight state · warn: needs a look · bad: broken · idle: not tracked here */
export type Tone = 'ok' | 'info' | 'warn' | 'bad' | 'idle'

export interface Cell {
  tone: Tone
  label: string
  /** Secondary text such as an age or publication mode. */
  detail?: string
  /** Hover text with the full reason and source commit. */
  title: string
}

export type Stage =
  | 'source'
  | 'accepted'
  | 'running'
  | 'published'
  | 'backup'
  | 'tasks'

export const STAGES: Array<{ key: Stage; label: string }> = [
  { key: 'source', label: 'Source' },
  { key: 'accepted', label: 'Accepted' },
  { key: 'running', label: 'Running' },
  { key: 'published', label: 'Published' },
  { key: 'backup', label: 'Backup' },
  { key: 'tasks', label: 'Tasks' },
]

export interface Signals {
  cells: Record<Stage, Cell>
  /** Higher sorts first; zero means nothing needs a look. */
  attention: number
  worst: Tone
  canPublish: boolean
}

const WEIGHT: Record<Tone, number> = {
  bad: 3,
  warn: 1,
  info: 0,
  ok: 0,
  idle: 0,
}
const RANK: Tone[] = ['bad', 'warn', 'info', 'ok', 'idle']
const NIGHTLY_FAILED = new Set(['failed', 'blocked', 'acceptance_failed'])

export function shortSha(sha: string | null | undefined): string {
  return sha ? sha.slice(0, 7) : ''
}

export function evidenceDate(value: DevelopmentEvidence['observed_at']) {
  if (value === null || value === undefined) return null
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  return Number.isNaN(date.getTime()) ? null : date
}

export function evidenceAge(value: DevelopmentEvidence['observed_at']) {
  const date = evidenceDate(value)
  return date ? formatTimeAgo(date.toISOString()) : undefined
}

function hint(evidence: DevelopmentEvidence, extra?: string): string {
  return [
    extra,
    evidence.reason,
    evidence.source_commit ? `Commit ${evidence.source_commit}` : null,
    evidenceDate(evidence.observed_at)?.toLocaleString(),
  ]
    .filter(Boolean)
    .join('\n')
}

function plural(count: number, noun: string) {
  return `${count} ${noun}${count === 1 ? '' : 's'}`
}

function sourceCell(dev: DevelopmentProjection): Cell {
  const working = dev.working_tree
  const head = working.source_commit
  if (working.state === 'error')
    return { tone: 'bad', label: 'unreadable', title: working.reason }
  const files = working.uncommitted ?? 0
  if (files > 0)
    return {
      tone: 'warn',
      label: plural(files, 'file'),
      detail: 'uncommitted',
      title: `${plural(files, 'uncommitted file')} on ${shortSha(head)}`,
    }
  return {
    tone: 'ok',
    label: shortSha(head) || 'clean',
    detail: head ? 'clean' : undefined,
    title: head ? `Clean working tree at ${head}` : working.reason,
  }
}

function autoPublished(dev: DevelopmentProjection) {
  return ['nightly', 'mirror'].includes(dev.publication.mode ?? '')
}

function acceptedCell(dev: DevelopmentProjection): Cell {
  const accepted = dev.accepted
  const age = evidenceAge(accepted.observed_at)
  switch (accepted.state) {
    case 'accepted':
      return {
        tone: 'ok',
        label: 'HEAD',
        detail: age,
        title: hint(
          accepted,
          accepted.check_count
            ? `${plural(accepted.check_count, 'check')} passed`
            : undefined,
        ),
      }
    case 'stale':
      return {
        // Nightly re-runs acceptance before publishing; mirror needs none.
        tone: autoPublished(dev) ? 'info' : 'warn',
        label: accepted.drift ? shortSha(accepted.source_commit) : 'outdated',
        detail: accepted.drift ? 'older commit' : 'inputs changed',
        title: hint(accepted),
      }
    case 'unavailable':
      return { tone: 'idle', label: 'none', title: accepted.reason }
    default:
      return {
        tone: 'bad',
        label: accepted.state.replaceAll('_', ' '),
        title: hint(accepted),
      }
  }
}

function runningCell(dev: DevelopmentProjection): Cell {
  const running = dev.running
  const head = dev.working_tree.source_commit
  const age = evidenceAge(running.observed_at)
  if (running.state === 'observed' || running.state === 'succeeded') {
    if (running.source_commit && running.source_commit === head)
      return { tone: 'ok', label: 'HEAD', detail: age, title: hint(running) }
    const acceptedHead =
      dev.accepted.state === 'accepted' && dev.accepted.source_commit === head
    return {
      tone: running.drift ? 'warn' : 'info',
      label: shortSha(running.source_commit),
      detail: !running.drift
        ? age
        : acceptedHead
          ? 'needs deploy'
          : 'differs from accepted',
      title: hint(
        running,
        !running.drift
          ? 'Running the accepted source; HEAD has moved on'
          : acceptedHead
            ? 'HEAD is accepted but not deployed'
            : 'Running source differs from the accepted source',
      ),
    }
  }
  if (running.state === 'unavailable')
    return { tone: 'idle', label: 'not deployed', title: running.reason }
  if (running.state === 'failed')
    return {
      tone: 'bad',
      label: 'deploy failed',
      detail: age,
      title: hint(running),
    }
  return { tone: 'bad', label: 'unverified', title: hint(running) }
}

/** Commits not yet published; prefers the backend count, which also trusts verified publication receipts. */
export function unpublished(dev: DevelopmentProjection, repo: RepoStatus) {
  return dev.working_tree.unpublished ?? repo.ahead
}

function publishedCell(dev: DevelopmentProjection, repo: RepoStatus): Cell {
  const publication = dev.publication
  const mode = publication.mode && publication.mode !== 'unknown'
  const modeLabel = mode ? publication.mode : undefined
  const nightly = publication.nightly
  const ahead = unpublished(dev, repo)
  const remote = dev.working_tree.remote_basis?.startsWith('Last verified')
    ? 'than the last verified publication'
    : `vs origin/${repo.branch} (local refs)`
  if (ahead > 0 && repo.behind > 0)
    return {
      tone: 'bad',
      label: `↑${ahead} ↓${repo.behind}`,
      detail: 'diverged',
      title: `Diverged ${remote}`,
    }
  if (repo.behind > 0)
    return {
      tone: 'warn',
      label: `↓${repo.behind}`,
      detail: 'pull',
      title: `${plural(repo.behind, 'commit')} behind ${remote}`,
    }
  if (publication.state === 'failed')
    return { tone: 'bad', label: 'failed', title: hint(publication) }
  if (publication.verdict === 'blocked')
    return {
      tone: 'bad',
      label: 'blocked',
      detail: publication.ci_state === 'failed' ? 'CI failed' : undefined,
      title: hint(
        publication,
        `Publication blocked: ${(publication.verdict_reason ?? 'unknown').replaceAll('_', ' ')}`,
      ),
    }
  const nightlyAt = evidenceDate(nightly?.observed_at ?? null)
  const publishedAt = evidenceDate(publication.observed_at)
  if (
    nightly?.outcome &&
    NIGHTLY_FAILED.has(nightly.outcome) &&
    (!publishedAt || (nightlyAt !== null && nightlyAt > publishedAt))
  )
    return {
      tone: 'bad',
      label: 'failed',
      detail: 'nightly',
      title: `Nightly ${nightly.outcome}: ${nightly.reason ?? 'no reason recorded'}`,
    }
  if (ahead > 0)
    return {
      tone: publication.mode === 'manual' ? 'warn' : 'info',
      label: `↑${ahead}`,
      detail: modeLabel,
      title: `${plural(ahead, 'commit')} ahead ${remote}${publication.mode === 'nightly' ? '; nightly publication pushes accepted source' : ''}`,
    }
  if (
    dev.working_tree.unpublished === null &&
    publication.state === 'unavailable'
  )
    return { tone: 'idle', label: 'no remote', title: publication.reason }
  // Pushed is not verified: only CI and security success on the source earns green.
  const unverified: Partial<Record<string, Cell>> = {
    published:
      publication.ci_state === 'not_applicable'
        ? {
            tone: 'ok',
            label: 'synced',
            detail: 'no CI',
            title: hint(
              publication,
              `In sync ${remote}; this repository has no CI`,
            ),
          }
        : {
            tone: 'warn',
            label: 'no CI',
            title: hint(
              publication,
              `Pushed ${remote}; no CI result for this source`,
            ),
          },
    pending: {
      tone: 'info',
      label: 'checks pending',
      title: hint(
        publication,
        `Pushed ${remote}; CI or security still pending`,
      ),
    },
    unknown: {
      tone: 'info',
      label: 'unverified',
      title: hint(
        publication,
        `In sync ${remote}; CI and security not verified`,
      ),
    },
  }
  const cell = publication.verdict ? unverified[publication.verdict] : undefined
  if (cell) return cell
  return {
    tone: 'ok',
    label: 'synced',
    detail: evidenceAge(publication.observed_at) ?? modeLabel,
    title: hint(publication, `In sync ${remote}`),
  }
}

function backupCell(dev: DevelopmentProjection): Cell {
  const { capture, offsite } = dev.recovery
  const age = evidenceAge(capture.observed_at)
  if (capture.state === 'unavailable')
    return { tone: 'idle', label: 'none', title: capture.reason }
  if (capture.state === 'running')
    return { tone: 'info', label: 'running', detail: age, title: hint(capture) }
  if (capture.state !== 'completed')
    return {
      tone: 'bad',
      label: capture.state.replaceAll('_', ' '),
      detail: age,
      title: hint(capture),
    }
  if (offsite.state === 'verified')
    return {
      tone: 'ok',
      label: age ?? 'done',
      detail: 'offsite',
      title: `Captured ${age ?? ''} and copied offsite`.trim(),
    }
  if (offsite.state === 'failed' || offsite.state === 'error')
    return {
      tone: 'bad',
      label: 'offsite failed',
      detail: age,
      title: hint(offsite),
    }
  return {
    tone: 'warn',
    label: age ?? 'local',
    detail: 'local only',
    title: hint(offsite, 'No verified offsite copy for the latest capture'),
  }
}

function tasksCell(dev: DevelopmentProjection): Cell {
  const blockers = dev.blockers
  const count = blockers.items.length
  if (blockers.state === 'unavailable')
    return {
      tone: 'warn',
      label: 'unknown',
      title: blockers.reason ?? 'Task store unavailable',
    }
  if (count === 0)
    return { tone: 'idle', label: '0', title: 'No blocked or failed tasks' }
  const failed = blockers.items.filter(
    (task) => task.status === 'failed',
  ).length
  return {
    tone: 'warn',
    label: `${count}${blockers.state === 'partial' ? '+' : ''}`,
    detail: failed === count ? 'failed' : failed ? 'need review' : 'blocked',
    title: blockers.items
      .slice(0, 6)
      .map((task) => `${task.status}: ${task.title}`)
      .join('\n'),
  }
}

export function deriveSignals(
  repo: RepoStatus,
  dev: DevelopmentProjection,
): Signals {
  const cells: Record<Stage, Cell> = {
    source: sourceCell(dev),
    accepted: acceptedCell(dev),
    running: runningCell(dev),
    published: publishedCell(dev, repo),
    backup: backupCell(dev),
    tasks: tasksCell(dev),
  }
  const tones = Object.values(cells).map((cell) => cell.tone)
  const accepted = dev.accepted
  return {
    cells,
    attention: tones.reduce((sum, tone) => sum + WEIGHT[tone], 0),
    worst: RANK.find((tone) => tones.includes(tone)) ?? 'idle',
    canPublish:
      accepted.state === 'accepted' &&
      accepted.full_coverage === true &&
      !!accepted.source_commit,
  }
}

export type Filter = 'attention' | Stage

export function matchesFilter(signals: Signals, filter: Filter | null) {
  if (!filter) return true
  if (filter === 'attention') return signals.attention > 0
  const tone = signals.cells[filter].tone
  return tone === 'warn' || tone === 'bad'
}
