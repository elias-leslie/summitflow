import clsx from 'clsx'
import type { DevelopmentProjection } from '@/lib/api/git'
import {
  type Cell,
  evidenceAge,
  type Signals,
  shortSha,
} from './developmentSignals'
import { TONE_DOT, TONE_TEXT } from './SignalCell'

interface Node {
  label: string
  sha: string | null | undefined
  cell: Cell
  note?: string
  reason?: string
}

/**
 * Where HEAD stands in the local lifecycle: each stop shows the commit it
 * holds, so a stage lagging behind HEAD reads as a different SHA.
 */
export function SourceLane({
  development,
  signals,
}: {
  development: DevelopmentProjection
  signals: Signals
}) {
  const { cells } = signals
  const head = development.working_tree.source_commit
  const flagged = (cell: Cell, reason: string) =>
    cell.tone === 'warn' || cell.tone === 'bad' ? reason : undefined
  const nodes: Node[] = [
    {
      label: 'HEAD',
      sha: head,
      cell: cells.source,
      note:
        cells.source.tone === 'warn'
          ? `${cells.source.label} uncommitted`
          : 'clean',
    },
    {
      label: 'Accepted',
      sha: development.accepted.source_commit,
      cell: cells.accepted,
      note: [
        development.accepted.check_count
          ? `${development.accepted.check_count} checks`
          : null,
        evidenceAge(development.accepted.observed_at),
      ]
        .filter(Boolean)
        .join(' · '),
      reason: flagged(cells.accepted, development.accepted.reason),
    },
    {
      label: 'Running',
      sha: development.running.source_commit,
      cell: cells.running,
      note: evidenceAge(development.running.observed_at),
      reason: flagged(cells.running, development.running.reason),
    },
    {
      label: 'Published',
      sha: development.publication.source_commit,
      cell: cells.published,
      note: [
        development.publication.mode,
        evidenceAge(development.publication.observed_at),
      ]
        .filter((part) => part && part !== 'unknown')
        .join(' · '),
      reason: flagged(cells.published, cells.published.title),
    },
  ]
  return (
    <ol className="grid grid-cols-2 gap-x-2 gap-y-3 sm:grid-cols-4">
      {nodes.map((node, index) => {
        const atHead = !!node.sha && node.sha === head
        return (
          <li key={node.label} className="relative min-w-0">
            {index > 0 && (
              <span
                aria-hidden="true"
                className="absolute -left-2 top-[7px] hidden h-px w-2 bg-slate-700 sm:block"
              />
            )}
            <div className="flex items-center gap-2">
              <span
                aria-hidden="true"
                className={clsx(
                  'h-3.5 w-3.5 shrink-0 rounded-full border-2 border-slate-950',
                  TONE_DOT[node.cell.tone],
                  atHead && 'ring-2 ring-emerald-400/30',
                )}
              />
              <span className="text-2xs font-medium uppercase tracking-[0.12em] text-slate-400">
                {node.label}
              </span>
              <span className="h-px flex-1 bg-slate-800" aria-hidden="true" />
            </div>
            <div className="mt-1 pl-5.5">
              <p
                className={clsx(
                  'font-mono text-xs',
                  node.sha ? TONE_TEXT[node.cell.tone] : 'text-slate-500',
                )}
                title={node.sha ?? undefined}
              >
                {node.sha
                  ? `${shortSha(node.sha)}${atHead && index > 0 ? ' = HEAD' : ''}`
                  : node.cell.label}
              </p>
              {node.note && (
                <p className="text-2xs text-slate-500">{node.note}</p>
              )}
              {node.reason && (
                <p className="mt-0.5 text-2xs leading-snug text-amber-200/80">
                  {node.reason}
                </p>
              )}
            </div>
          </li>
        )
      })}
    </ol>
  )
}
