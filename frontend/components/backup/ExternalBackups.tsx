'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import {
  type ExternalBackupSource,
  fetchExternalBackups,
} from '@/lib/api/backups-infra'
import { formatTimeAgo } from '@/lib/format'
import { POLL_NOTIFICATIONS } from '@/lib/polling'

const FREQUENCY: Record<string, string> = {
  hourly: 'Hourly',
  four_hourly: 'Every 4 hours',
  daily: 'Daily',
  weekly: 'Weekly',
  monthly: 'Monthly',
}

function lastLine(source: ExternalBackupSource): string {
  if (source.last_status === 'running') return 'Running now'
  if (!source.last_success_at)
    return source.last_error ?? 'No successful run found'
  return `Last good run ${formatTimeAgo(source.last_success_at)}`
}

/** Hours read badly past two days: "336 h" is two weeks. */
export function staleAfter(hours: number): string {
  if (hours < 48) return `${Math.round(hours)} h`
  const days = Math.round(hours / 24)
  return days % 7 === 0
    ? `${days / 7} ${days === 7 ? 'week' : 'weeks'}`
    : `${days} days`
}

function whereLine(source: ExternalBackupSource): string {
  return source.kind === 'systemd_unit'
    ? `Timer ${source.target}`
    : `Files ${source.target}`
}

export function ExternalBackups() {
  const { data, error, isLoading } = useQuery({
    queryKey: ['backups', 'external'],
    queryFn: fetchExternalBackups,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  return (
    <section aria-labelledby="external-backups-title" className="space-y-2">
      <div>
        <h3
          id="external-backups-title"
          className="text-sm font-medium text-slate-100"
        >
          Run by other projects
        </h3>
        <p className="text-xs text-slate-500">
          SummitFlow doesn't run these, but tracks whether they're fresh.
          Nightshift reads the same record.
        </p>
      </div>
      {isLoading && (
        <div className="h-14 animate-pulse rounded-lg bg-slate-800/40" />
      )}
      {error && (
        <p className="text-xs text-rose-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </p>
      )}
      {data && data.sources.length === 0 && (
        <p className="text-xs text-slate-500">None tracked.</p>
      )}
      <ul className="grid gap-2 md:grid-cols-2">
        {data?.sources.map((source) => (
          <li
            key={source.id}
            className={clsx(
              'rounded-lg border p-3 text-sm',
              source.ok
                ? 'border-emerald-500/20 bg-emerald-500/5'
                : 'border-rose-500/25 bg-rose-500/5',
            )}
          >
            <div className="flex items-start justify-between gap-2">
              <span className="font-medium text-slate-100">
                {source.name ?? source.id}
              </span>
              <span
                className={clsx(
                  'shrink-0 text-[10px] uppercase tracking-[0.14em]',
                  source.ok ? 'text-emerald-300' : 'text-rose-300',
                )}
              >
                {source.ok ? 'Fresh' : 'Stale'}
              </span>
            </div>
            <div className="mt-1.5 space-y-0.5 text-xs text-slate-300">
              <div>{lastLine(source)}</div>
              <div className="text-slate-500">
                {FREQUENCY[source.frequency] ?? source.frequency} · stale after{' '}
                {staleAfter(source.stale_after_hours)}
                {source.owner_project && ` · ${source.owner_project}`}
              </div>
              <div className="break-all font-mono text-[11px] text-slate-500">
                {whereLine(source)}
              </div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
