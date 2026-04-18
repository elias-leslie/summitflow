'use client'

import { clsx } from 'clsx'
import { Loader2, Play, Wrench } from 'lucide-react'
import { useState } from 'react'
import type {
  AutonomousExecutionSettings,
  MaintenanceRun,
  RoutineUpkeepStatus,
} from '@/lib/api'
import { Input } from '../ui/input'
import { Label } from '../ui/label'

interface RoutineUpkeepSectionProps {
  settings: Pick<
    AutonomousExecutionSettings,
    'upkeep_enabled' | 'upkeep_frequency_minutes' | 'upkeep_batch_limit'
  >
  status?: RoutineUpkeepStatus
  isPending: boolean
  isRunning: boolean
  onEnabledToggle: () => void
  onFrequencyChange: (value: string) => void
  onBatchLimitChange: (value: string) => void
  onRunNow: () => void
}

function summaryNumber(
  run: MaintenanceRun | null | undefined,
  key: string,
): number {
  const value = run?.summary?.[key]
  return typeof value === 'number' ? value : 0
}

function dispatchedCount(run: MaintenanceRun | null | undefined): number {
  const dispatch = run?.summary?.dispatch
  if (!dispatch || typeof dispatch !== 'object') return 0
  const value = (dispatch as Record<string, unknown>).dispatched
  return typeof value === 'number' ? value : 0
}

function taskCountLabel(count: number): string {
  return `${count} ${count === 1 ? 'task' : 'tasks'}`
}

function statusLabel(
  settings: RoutineUpkeepSectionProps['settings'],
  latest: MaintenanceRun | null | undefined,
  isRunning: boolean,
): string {
  if (!settings.upkeep_enabled) return 'Disabled'
  if (isRunning) return 'Running'
  if (!latest) return 'Never run'
  if (latest.status === 'failed') return 'Failed'
  const created = summaryNumber(latest, 'tasks_created')
  return `Completed · ${taskCountLabel(created)}`
}

function statusTone(label: string): string {
  if (label === 'Running')
    return 'border-amber-500/30 bg-amber-500/10 text-amber-200'
  if (label === 'Failed')
    return 'border-rose-500/30 bg-rose-500/10 text-rose-200'
  if (label.startsWith('Completed'))
    return 'border-emerald-500/30 bg-emerald-500/10 text-emerald-200'
  return 'border-slate-600 bg-slate-800/60 text-slate-300'
}

function formatRunTime(value: string): string {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function historyStatusTone(status: string): string {
  if (status === 'failed') return 'text-rose-300'
  if (status === 'blocked') return 'text-amber-300'
  if (status === 'completed') return 'text-emerald-300'
  return 'text-slate-300'
}

function HistoryRows({ runs }: { runs: MaintenanceRun[] }) {
  const [expanded, setExpanded] = useState(false)
  if (runs.length === 0) {
    return <p className="text-xs text-slate-500">No runs recorded yet.</p>
  }
  const visibleRuns = expanded ? runs.slice(0, 5) : runs.slice(0, 3)
  return (
    <div className="space-y-2">
      {visibleRuns.map((run) => (
        <div
          key={run.id}
          className="flex items-center justify-between gap-3 rounded-lg border border-slate-700/60 bg-slate-900/35 px-3 py-2 text-xs"
        >
          <div className="min-w-0">
            <span
              className={clsx('font-medium', historyStatusTone(run.status))}
            >
              {run.status}
            </span>
            <span className="ml-2 text-slate-500">
              {formatRunTime(run.started_at)}
            </span>
          </div>
          <div className="shrink-0 text-slate-400">
            {taskCountLabel(summaryNumber(run, 'tasks_created'))}
          </div>
        </div>
      ))}
      {runs.length > 3 && (
        <button
          type="button"
          onClick={() => setExpanded(!expanded)}
          className="text-xs text-amber-300 hover:text-amber-200"
        >
          {expanded ? 'Show less' : 'Show more'}
        </button>
      )}
    </div>
  )
}

export function RoutineUpkeepSection({
  settings,
  status,
  isPending,
  isRunning,
  onEnabledToggle,
  onFrequencyChange,
  onBatchLimitChange,
  onRunNow,
}: RoutineUpkeepSectionProps) {
  const latest = status?.latest
  const label = statusLabel(settings, latest, isRunning)
  const created = summaryNumber(latest, 'tasks_created')
  const dispatched = dispatchedCount(latest)
  const disabled = !settings.upkeep_enabled || isPending || isRunning

  return (
    <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h3 className="text-base font-medium text-slate-100 flex items-center gap-2">
            <Wrench className="w-4 h-4 text-slate-400" />
            Routine Upkeep
          </h3>
          <p className="text-xs text-slate-400 mt-2">
            Finds upkeep work and routes it through normal autonomous tasks.
          </p>
        </div>
        <button
          type="button"
          onClick={onEnabledToggle}
          disabled={isPending}
          role="switch"
          aria-checked={settings.upkeep_enabled}
          aria-label={
            settings.upkeep_enabled
              ? 'Disable routine upkeep'
              : 'Enable routine upkeep'
          }
          className={clsx(
            'relative h-6 w-12 rounded-full transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500/40 focus-visible:ring-offset-2 focus-visible:ring-offset-slate-900',
            settings.upkeep_enabled ? 'bg-amber-500' : 'bg-slate-600',
          )}
        >
          <span
            className={clsx(
              'absolute top-1 h-4 w-4 rounded-full bg-slate-100 shadow-sm transition-transform',
              settings.upkeep_enabled ? 'translate-x-7' : 'translate-x-1',
            )}
          />
        </button>
      </div>

      <div
        className={clsx(
          'rounded-lg border px-3 py-2 text-sm',
          statusTone(label),
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{label}</span>
          {isRunning && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
          {latest && label !== 'Never run' && (
            <span className="text-xs opacity-80">
              {created} created, {dispatched} dispatched
            </span>
          )}
        </div>
        {latest?.error_message && (
          <p className="mt-1 text-xs opacity-85">{latest.error_message}</p>
        )}
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <Label
            htmlFor="upkeep-frequency"
            className="text-slate-200 mb-2 block"
          >
            Cadence
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            How often to run routine upkeep (15-1440 min)
          </p>
          <Input
            id="upkeep-frequency"
            type="number"
            min={15}
            max={1440}
            value={settings.upkeep_frequency_minutes}
            onChange={(event) => onFrequencyChange(event.target.value)}
            disabled={isPending}
            className="max-w-[200px]"
          />
        </div>
        <div>
          <Label htmlFor="upkeep-batch" className="text-slate-200 mb-2 block">
            Max tasks per run
          </Label>
          <p className="text-xs text-slate-400 mb-3">
            Caps how many tasks a single upkeep run can create.
          </p>
          <Input
            id="upkeep-batch"
            type="number"
            min={1}
            max={10}
            value={settings.upkeep_batch_limit}
            onChange={(event) => onBatchLimitChange(event.target.value)}
            disabled={isPending}
            className="max-w-[200px]"
          />
        </div>
      </div>

      <div className="border-t border-slate-700/70 pt-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <p className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
            Recent runs
          </p>
          <button
            type="button"
            onClick={onRunNow}
            disabled={disabled}
            className={clsx(
              'inline-flex items-center gap-2 rounded-lg border px-3 py-2 text-xs font-medium transition-colors',
              disabled
                ? 'border-slate-700 bg-slate-800/60 text-slate-500'
                : 'border-amber-500/40 bg-amber-500/15 text-amber-200 hover:bg-amber-500/25',
            )}
          >
            {isRunning ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Play className="h-3.5 w-3.5" />
            )}
            Run now
          </button>
        </div>
        <div className="mt-3">
          <HistoryRows runs={status?.recent ?? []} />
        </div>
      </div>
    </div>
  )
}
