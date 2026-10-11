'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { useState } from 'react'
import { type MaintenanceRun, runtimeApi } from '@/lib/api/runtime'
import { formatDuration, formatTimeAgo } from '@/lib/format'
import { POLL_NOTIFICATIONS } from '@/lib/polling'

type Severity = 'ok' | 'warn' | 'fail'

const SEVERITY_RANK: Record<Severity, number> = { ok: 0, warn: 1, fail: 2 }

function severity(status: string): Severity {
  if (status === 'failed' || status === 'blocked') return 'fail'
  if (status === 'completed' || status === 'success') return 'ok'
  return 'warn'
}

function workflowLabel(name: string): string {
  return name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function rowsCleanedLabel(run: MaintenanceRun): string {
  const count = run.rows_cleaned ?? 0
  return `${count} ${count === 1 ? 'row' : 'rows'} cleaned`
}

function overallSummary(runs: MaintenanceRun[]): string {
  if (runs.length === 0) return 'No runs recorded'
  const counts = new Map<string, number>()
  for (const run of runs) {
    if (severity(run.status) !== 'ok') {
      counts.set(run.status, (counts.get(run.status) ?? 0) + 1)
    }
  }
  const newest = runs.reduce((a, b) => (a.started_at > b.started_at ? a : b))
  const health =
    counts.size === 0
      ? 'All workflows succeeded'
      : [...counts.entries()]
          .map(([status, count]) => `${count} ${status}`)
          .join(', ')
  return `${health} · last run ${formatTimeAgo(newest.started_at)}`
}

function worstSeverity(runs: MaintenanceRun[]): Severity | null {
  if (runs.length === 0) return null
  return runs
    .map((run) => severity(run.status))
    .reduce((a, b) => (SEVERITY_RANK[b] > SEVERITY_RANK[a] ? b : a))
}

function tone(status: string): string {
  const level = severity(status)
  if (level === 'fail') return 'border-rose-500/20 bg-rose-500/5 text-rose-100'
  if (level === 'ok') {
    return 'border-emerald-500/20 bg-emerald-500/5 text-emerald-100'
  }
  return 'border-amber-500/20 bg-amber-500/5 text-amber-100'
}

export function MaintenanceStatusCard() {
  const [expanded, setExpanded] = useState(false)
  const { data, error, isLoading } = useQuery({
    queryKey: ['runtime', 'maintenance'],
    queryFn: runtimeApi.getMaintenanceStatus,
    refetchInterval: POLL_NOTIFICATIONS,
  })

  if (isLoading) {
    return <div className="h-12 animate-pulse rounded-lg bg-slate-800/40" />
  }

  if (error || !data) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-4 py-3">
        <span className="text-sm font-medium text-slate-100">Maintenance</span>
        <span className="ml-3 text-sm text-red-300">
          {error instanceof Error ? error.message : 'Unavailable'}
        </span>
      </div>
    )
  }

  const latestRuns = Object.values(data.latest)
  const worst = worstSeverity(latestRuns)

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/50">
      <button
        type="button"
        onClick={() => setExpanded(!expanded)}
        className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-slate-800/30"
      >
        <div
          className={clsx(
            'h-2 w-2 rounded-full',
            worst === 'fail'
              ? 'bg-rose-500'
              : worst === 'warn'
                ? 'bg-amber-400'
                : worst === 'ok'
                  ? 'bg-emerald-500'
                  : 'bg-slate-600',
          )}
        />
        <span className="text-sm font-medium text-slate-100">Maintenance</span>
        <span className="flex-1 text-xs text-slate-500">
          {overallSummary(latestRuns)}
        </span>
        <svg
          width="12"
          height="12"
          viewBox="0 0 12 12"
          fill="none"
          className={clsx(
            'text-slate-500 transition-transform duration-200',
            expanded && 'rotate-180',
          )}
        >
          <path
            d="M3 4.5L6 7.5L9 4.5"
            stroke="currentColor"
            strokeWidth="1.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        </svg>
      </button>

      {expanded && (
        <div className="grid gap-2 border-t border-slate-800/60 px-4 py-4 md:grid-cols-2 lg:grid-cols-3">
          {latestRuns.length === 0 ? (
            <p className="text-xs text-slate-500">
              No maintenance runs recorded yet.
            </p>
          ) : (
            latestRuns.map((run) => (
              <div
                key={run.workflow_name}
                className={clsx(
                  'rounded-lg border p-3 text-sm',
                  tone(run.status),
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">
                    {workflowLabel(run.workflow_name)}
                  </span>
                  <span className="text-[10px] uppercase tracking-[0.14em]">
                    {run.status}
                  </span>
                </div>
                <div className="mt-2 space-y-0.5 text-xs text-slate-300">
                  <div title={new Date(run.started_at).toLocaleString()}>
                    Started {formatTimeAgo(run.started_at)}
                    {run.duration_ms != null &&
                      ` · took ${formatDuration(run.duration_ms)}`}
                  </div>
                  <div>{rowsCleanedLabel(run)}</div>
                </div>
                {run.error_message && (
                  <div className="mt-2 text-xs text-rose-200">
                    {run.error_message}
                  </div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
