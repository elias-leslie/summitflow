/**
 * TaskDetail - Detail panel for Celery tasks
 *
 * Shows schedule, stats, dependencies, table interactions.
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import { formatDate, formatDuration, formatNumber } from '@/lib/format'
import { cn } from '@/lib/utils'

interface TaskDetailProps {
  entry: ExplorerEntry
}

export function TaskDetail({ entry }: TaskDetailProps) {
  const meta = entry.metadata
  const readsTables = meta.reads_tables ?? []
  const writesTables = meta.writes_tables ?? []
  const dependsOn = meta.depends_on_tasks ?? []
  const calledBy = meta.called_by ?? []

  return (
    <div className="space-y-4">
      {/* Task path */}
      <div>
        <span className="text-xs text-slate-500 uppercase tracking-wide">
          Task Path
        </span>
        <p className="font-mono text-sm text-slate-300 mt-1">
          {meta.task_path || entry.path}
        </p>
      </div>

      {/* Schedule info */}
      {meta.schedule_type && (
        <div className="grid grid-cols-2 gap-4">
          <div>
            <span className="text-xs text-slate-500 uppercase tracking-wide">
              Schedule Type
            </span>
            <p className="text-sm text-slate-200 mt-1 capitalize">
              {meta.schedule_type}
            </p>
          </div>
          <div>
            <span className="text-xs text-slate-500 uppercase tracking-wide">
              Schedule
            </span>
            <p className="text-sm text-slate-200 mt-1">
              {meta.schedule_human || meta.schedule_value || '-'}
            </p>
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Success (7d)
          </span>
          <p className="font-mono text-sm text-emerald-400 mt-1">
            {formatNumber(meta.success_count_7d)}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Failures (7d)
          </span>
          <p
            className={cn(
              'font-mono text-sm mt-1',
              (meta.failure_count_7d ?? 0) > 0
                ? 'text-red-400'
                : 'text-slate-400',
            )}
          >
            {formatNumber(meta.failure_count_7d)}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Success Rate
          </span>
          <p
            className={cn(
              'font-mono text-sm mt-1',
              meta.success_rate_pct != null && meta.success_rate_pct >= 99
                ? 'text-emerald-400'
                : meta.success_rate_pct != null && meta.success_rate_pct < 90
                  ? 'text-amber-400'
                  : 'text-slate-200',
            )}
          >
            {meta.success_rate_pct != null
              ? `${meta.success_rate_pct.toFixed(1)}%`
              : '-'}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Avg Duration
          </span>
          <p className="font-mono text-sm text-slate-200 mt-1">
            {formatDuration(meta.avg_duration_ms)}
          </p>
        </div>
      </div>

      {/* Last run */}
      {meta.last_run_at && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Last Run
          </span>
          <p className="text-sm text-slate-300 mt-1">
            {formatDate(meta.last_run_at)}
          </p>
        </div>
      )}

      {/* Table interactions */}
      {(readsTables.length > 0 || writesTables.length > 0) && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Table Interactions
          </span>
          <div className="mt-2 space-y-2">
            {readsTables.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Reads:</span>
                <span className="ml-2 text-xs font-mono text-blue-400">
                  {readsTables.join(', ')}
                </span>
              </div>
            )}
            {writesTables.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Writes:</span>
                <span className="ml-2 text-xs font-mono text-amber-400">
                  {writesTables.join(', ')}
                </span>
              </div>
            )}
          </div>
        </div>
      )}

      {/* Dependencies */}
      {(dependsOn.length > 0 || calledBy.length > 0) && (
        <div className="pt-2 border-t border-slate-700/50">
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Dependencies
          </span>
          <div className="mt-2 space-y-2">
            {dependsOn.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Depends on:</span>
                <span className="ml-2 text-xs font-mono text-purple-400">
                  {dependsOn.join(', ')}
                </span>
              </div>
            )}
            {calledBy.length > 0 && (
              <div>
                <span className="text-xs text-slate-500">Called by:</span>
                <span className="ml-2 text-xs font-mono text-cyan-400">
                  {calledBy.join(', ')}
                </span>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
