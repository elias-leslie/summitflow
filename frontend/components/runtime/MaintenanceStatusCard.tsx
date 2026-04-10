'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { useState } from 'react'
import { runtimeApi, type MaintenanceRun } from '@/lib/api/runtime'
import { POLL_NOTIFICATIONS } from '@/lib/polling'

function taskCount(run: MaintenanceRun | undefined): number {
  const value = run?.summary?.tasks_created
  return typeof value === 'number' ? value : run?.rows_cleaned ?? 0
}

function workflowLabel(name: string): string {
  return name
    .split('_')
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ')
}

function routineSummary(run: MaintenanceRun | undefined): string {
  if (!run) return 'Routine upkeep never run'
  const count = taskCount(run)
  const label = `${count} ${count === 1 ? 'task' : 'tasks'}`
  return `Routine upkeep ${run.status} · ${label}`
}

function tone(status: string | undefined): string {
  if (status === 'failed' || status === 'blocked') {
    return 'border-rose-500/20 bg-rose-500/5 text-rose-100'
  }
  if (status === 'completed' || status === 'success') {
    return 'border-emerald-500/20 bg-emerald-500/5 text-emerald-100'
  }
  return 'border-slate-600/40 bg-slate-800/30 text-slate-300'
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

  const routine = data.latest.routine_upkeep
  const latestRuns = Object.values(data.latest)

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
            routine?.status === 'failed' ? 'bg-rose-500' : routine ? 'bg-emerald-500' : 'bg-slate-600',
          )}
        />
        <span className="text-sm font-medium text-slate-100">Maintenance</span>
        <span className="flex-1 text-xs text-slate-500">{routineSummary(routine)}</span>
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
          <path d="M3 4.5L6 7.5L9 4.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {expanded && (
        <div className="grid gap-2 border-t border-slate-800/60 px-4 py-4 md:grid-cols-2 lg:grid-cols-3">
          {latestRuns.length === 0 ? (
            <p className="text-xs text-slate-500">No maintenance runs recorded yet.</p>
          ) : (
            latestRuns.map((run) => (
              <div
                key={run.workflow_name}
                className={clsx('rounded-lg border p-3 text-sm', tone(run.status))}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{workflowLabel(run.workflow_name)}</span>
                  <span className="text-[10px] uppercase tracking-[0.14em]">{run.status}</span>
                </div>
                <div className="mt-2 text-xs text-slate-300">
                  {taskCount(run)} tasks
                </div>
                {run.error_message && (
                  <div className="mt-2 text-xs text-rose-200">{run.error_message}</div>
                )}
              </div>
            ))
          )}
        </div>
      )}
    </div>
  )
}
