'use client'

import { useQuery } from '@tanstack/react-query'
import { getEventsForTrace } from '@/lib/api/events'
import type { VerificationResult } from '@/lib/api/tasks-types-core'
import { formatDate, formatTimeAgo } from '@/lib/format'

/** Task events (pause/resume reasons, progress notes, closeout) are recorded with the task id as their trace. */
const HISTORY_LIMIT = 1000

export function useTaskHistory(
  projectId: string,
  taskId: string,
  status?: string,
) {
  return useQuery({
    // Status is in the key so a pause or reopen from the dialog reads fresh history.
    queryKey: ['task-history', projectId, taskId, status],
    queryFn: () =>
      getEventsForTrace(projectId, taskId, {
        visibility: 'user',
        limit: HISTORY_LIMIT,
      }),
    staleTime: 30_000,
  })
}

/**
 * The last reason given with a pause, and when. A pause or reopen without a reason records
 * nothing, so a reason followed by a reopen or close belongs to an earlier pause.
 */
export function latestPauseReason(
  events: Array<{ message: string | null; timestamp: string }> | undefined,
): { reason: string; at: string } | null {
  const latest = [...(events ?? [])]
    .reverse()
    .find((event) => /^(Paused|Reopened|Closed): /.test(event.message ?? ''))
  return latest?.message?.startsWith('Paused: ')
    ? { reason: latest.message.slice('Paused: '.length), at: latest.timestamp }
    : null
}

/** Why a paused task is paused: the reason given with the last pause. */
export function PauseReason({
  projectId,
  taskId,
}: {
  projectId: string
  taskId: string
}) {
  const history = useTaskHistory(projectId, taskId, 'paused')
  if (history.isLoading) return null
  const paused = history.isError ? null : latestPauseReason(history.data)
  return (
    <section className="rounded-lg border border-amber-800/30 bg-amber-950/20 p-3">
      <h4 className="mb-1 text-xs font-mono uppercase tracking-wider text-amber-400/80">
        Why it's paused
      </h4>
      {paused && (
        <p className="mb-0.5 text-2xs text-slate-500">
          Last reason given, {formatTimeAgo(paused.at)}
        </p>
      )}
      <p className="whitespace-pre-wrap break-words text-sm text-slate-300">
        {history.isError
          ? 'Could not load the pause reason.'
          : (paused?.reason ?? 'No reason was given when it was paused.')}
      </p>
    </section>
  )
}

/** Everything recorded on the task, newest first. */
export function TaskHistory({
  projectId,
  taskId,
  status,
}: {
  projectId: string
  taskId: string
  status?: string
}) {
  const history = useTaskHistory(projectId, taskId, status)
  const entries = (history.data ?? []).filter((event) => event.message)
  return (
    <section>
      <h4 className="mb-2 text-xs font-mono uppercase tracking-wider text-slate-500">
        History
      </h4>
      {history.isLoading ? (
        <p className="text-sm text-slate-500">Loading history…</p>
      ) : history.isError ? (
        <p role="alert" className="text-sm text-rose-300">
          Could not load the task history.
        </p>
      ) : !entries.length ? (
        <p className="text-sm text-slate-500">Nothing recorded on this task.</p>
      ) : (
        <ol className="space-y-2">
          {(history.data?.length ?? 0) >= HISTORY_LIMIT && (
            <li className="text-2xs text-amber-300">
              Showing the first {HISTORY_LIMIT} entries; newer ones are not
              shown.
            </li>
          )}
          {[...entries].reverse().map((event) => (
            <li key={event.id} className="text-sm">
              <time
                dateTime={event.timestamp}
                title={formatDate(event.timestamp)}
                className="block text-2xs text-slate-500"
              >
                {formatTimeAgo(event.timestamp)}
              </time>
              <p
                className={
                  event.level === 'error'
                    ? 'whitespace-pre-wrap break-words text-rose-300'
                    : 'whitespace-pre-wrap break-words text-slate-300'
                }
              >
                {event.message}
              </p>
            </li>
          ))}
        </ol>
      )}
    </section>
  )
}

interface Closeout {
  message?: string
  source_sha?: string
  paths?: string[]
  completed_at?: string
}

interface Acceptance {
  outcome?: string
  coverage?: string
  check_count?: number
}

function record(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null
}

/** The closeout st done records: its summary, source commit, changed files and acceptance result. */
export function readCloseout(result: VerificationResult | null | undefined) {
  const raw = record(result)
  const closeout = record(raw?.closeout) as Closeout | null
  if (!closeout) return null
  const acceptance = record(raw?.acceptance) as Acceptance | null
  return {
    message: typeof closeout.message === 'string' ? closeout.message : '',
    commit: typeof closeout.source_sha === 'string' ? closeout.source_sha : '',
    paths: Array.isArray(closeout.paths)
      ? closeout.paths.filter((path) => typeof path === 'string')
      : [],
    acceptance: acceptance?.outcome
      ? acceptance.outcome === 'pass'
        ? `Passed${acceptance.check_count ? ` (${acceptance.check_count} checks)` : ''}${acceptance.coverage === 'full' ? ', full run' : ''}`
        : acceptance.outcome === 'fail'
          ? 'Failed'
          : `Recorded as ${acceptance.outcome}`
      : null,
  }
}

export function CloseoutSection({
  result,
}: {
  result: VerificationResult | null | undefined
}) {
  const closeout = readCloseout(result)
  if (!closeout) return null
  return (
    <section>
      <h4 className="mb-2 text-xs font-mono uppercase tracking-wider text-slate-500">
        How it was finished
      </h4>
      <div className="space-y-2 rounded-lg border border-slate-700/30 bg-slate-800/40 p-3 text-sm">
        {closeout.message && (
          <p className="whitespace-pre-wrap break-words text-slate-300">
            {closeout.message}
          </p>
        )}
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
          {closeout.commit && (
            <>
              <dt className="text-slate-500">Source commit</dt>
              <dd className="font-mono text-slate-300" title={closeout.commit}>
                {closeout.commit.slice(0, 9)}
              </dd>
            </>
          )}
          {closeout.acceptance && (
            <>
              <dt className="text-slate-500">Acceptance</dt>
              <dd className="text-slate-300">{closeout.acceptance}</dd>
            </>
          )}
          {closeout.paths.length > 0 && (
            <>
              <dt className="text-slate-500">Files</dt>
              <dd className="min-w-0">
                <ul className="space-y-0.5 font-mono text-slate-400">
                  {closeout.paths.map((path) => (
                    <li key={path} className="break-all">
                      {path}
                    </li>
                  ))}
                </ul>
              </dd>
            </>
          )}
        </dl>
      </div>
    </section>
  )
}
