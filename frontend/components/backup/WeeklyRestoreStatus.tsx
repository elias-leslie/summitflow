'use client'

import { clsx } from 'clsx'
import Link from 'next/link'
import type {
  BackupHealthResponse,
  CriticalRestoreHealth,
} from '@/lib/api/backups'
import { formatDate } from '@/lib/format'

const STATUS: Record<
  CriticalRestoreHealth['status'],
  { label: string; tone: string }
> = {
  verified: { label: 'Passed', tone: 'text-emerald-300' },
  failed: { label: 'Failed', tone: 'text-rose-300' },
  pending: { label: 'Pending', tone: 'text-amber-300' },
  running: { label: 'Running', tone: 'text-sky-300' },
  stale: { label: 'Overdue', tone: 'text-amber-300' },
  untested: { label: 'Not tested', tone: 'text-amber-300' },
  unavailable: { label: 'Unavailable', tone: 'text-slate-400' },
}

function qualification(restore: CriticalRestoreHealth): string | null {
  if (restore.latest_attempt?.status === 'running') {
    return restore.status === 'failed'
      ? 'Latest attempt is recorded as running; the previous failure remains unresolved.'
      : 'The latest restore attempt is recorded as running.'
  }
  if (restore.status === 'failed') {
    switch (restore.latest_attempt?.reason) {
      case 'mapped-links-unresolved':
        return 'Required configuration links could not be restored.'
      case 'repository-locked':
        return 'The repository was locked; this attempt did not verify recovery.'
      default:
        return 'The combined restore failed; recovery is not verified.'
    }
  }
  switch (restore.status) {
    case 'pending':
      return 'Required sources need an offsite-verified recovery point.'
    case 'stale':
      return 'The weekly combined restore is overdue.'
    case 'untested':
      return 'No successful combined restore is recorded.'
    case 'unavailable':
      return 'The repository restore result is unavailable.'
    default:
      return null
  }
}

export function WeeklyRestoreStatus({
  health,
  isLoading,
  error,
  onRefresh,
}: {
  health: BackupHealthResponse | undefined
  isLoading: boolean
  error: Error | null
  onRefresh: () => void
}) {
  const sourceName = (id: string) =>
    health?.sources.find((source) => source.source_id === id)?.source_name ?? id
  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/30 p-4 space-y-3">
      <div>
        <h3 className="text-sm font-medium text-slate-100">
          Weekly critical restore
        </h3>
        <p className="mt-0.5 text-xs text-slate-400">
          Combined offsite configuration and infrastructure restore. Host boot
          recovery is a separate check.
        </p>
      </div>
      {error && (
        <div className="space-y-2">
          <p role="alert" className="text-xs text-rose-300">
            Backup health refresh failed.{' '}
            {health
              ? 'Showing the last received results.'
              : 'Weekly restore status is unavailable.'}
          </p>
          <button
            type="button"
            onClick={onRefresh}
            className="btn-secondary text-xs"
          >
            Retry backup health
          </button>
        </div>
      )}
      {isLoading ? (
        <p role="status" className="text-xs text-slate-400">
          Loading weekly restore status…
        </p>
      ) : health?.repositories === undefined ? (
        !error && (
          <p className="text-xs text-slate-400">
            Weekly restore status is unavailable.
          </p>
        )
      ) : health.repositories.length === 0 ? (
        <p className="text-xs text-slate-400">
          No backup repositories are configured for the weekly restore.
        </p>
      ) : (
        <ul className="space-y-3">
          {health.repositories.map((repository) => {
            const restore = repository.critical_restore
            const status = STATUS[restore.status]
            const attempt = restore.latest_attempt
            const message = qualification(restore)
            return (
              <li
                key={repository.backend_id}
                className="border-t border-slate-800/60 pt-3 space-y-1.5 text-xs"
              >
                <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <span className="min-w-0 break-words font-medium text-slate-200">
                    {repository.backend_name}
                  </span>
                  <span className={clsx('font-medium', status.tone)}>
                    {status.label}
                  </span>
                </div>
                <p className="text-slate-400">
                  Last passed:{' '}
                  {restore.last_success_at
                    ? formatDate(restore.last_success_at)
                    : 'Never recorded'}
                </p>
                {message && <p className={status.tone}>{message}</p>}
                {attempt?.failed_source_id && (
                  <p className="text-rose-300">
                    Failed source:{' '}
                    <Link
                      className="underline underline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400"
                      href={`/backups/${encodeURIComponent(attempt.failed_source_id)}`}
                    >
                      {sourceName(attempt.failed_source_id)}
                    </Link>
                  </p>
                )}
                {attempt && (
                  <p className="text-slate-400">
                    Latest attempt:{' '}
                    {attempt.status === 'verified'
                      ? 'Passed'
                      : attempt.status === 'failed'
                        ? 'Failed'
                        : 'Running'}
                    {(attempt.completed_at ?? attempt.attempted_at) &&
                      ` on ${formatDate((attempt.completed_at ?? attempt.attempted_at)!)}`}
                    {attempt.cached &&
                      attempt.status === 'failed' &&
                      '. Saved failure; unchanged inputs have not been retried.'}
                  </p>
                )}
                <details className="pt-1">
                  <summary className="cursor-pointer text-slate-400 focus-visible:outline focus-visible:outline-2 focus-visible:outline-phosphor-400">
                    Restore scope and evidence
                  </summary>
                  <dl className="mt-2 space-y-1 text-slate-400 break-words">
                    <div>
                      <dt className="inline text-slate-300">
                        Required sources:{' '}
                      </dt>
                      <dd className="inline">
                        {restore.required_source_ids
                          .map(sourceName)
                          .join(', ') || 'None recorded'}
                      </dd>
                    </div>
                    <div>
                      <dt className="inline text-slate-300">
                        Last passed sources:{' '}
                      </dt>
                      <dd className="inline">
                        {restore.verified_source_ids
                          .map(sourceName)
                          .join(', ') || 'None recorded'}
                      </dd>
                    </div>
                    {restore.missing_source_ids.length > 0 && (
                      <div>
                        <dt className="inline text-amber-300">
                          Missing offsite-verified sources:{' '}
                        </dt>
                        <dd className="inline">
                          {restore.missing_source_ids
                            .map(sourceName)
                            .join(', ')}
                        </dd>
                      </div>
                    )}
                  </dl>
                </details>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
