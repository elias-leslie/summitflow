import {
  AlertTriangle,
  Check,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { CHECK_TYPE_COLORS } from './HealthConstants'
import type { ActivityFilter, CheckResult } from './HealthTypes'
import { formatFilePath, formatRelativeTime } from './HealthUtils'

interface ActivityFeedProps {
  projectId: string
  items: CheckResult[]
}

export function ActivityFeed({ projectId, items }: ActivityFeedProps) {
  const [filter, setFilter] = useState<ActivityFilter>('all')
  const [expandedId, setExpandedId] = useState<number | null>(null)

  const filteredActivity = items.filter((item) => {
    if (filter === 'fixed') return item.fixed_at !== null
    if (filter === 'escalated') return item.escalation_task_id !== null
    return true
  })

  return (
    <div className="col-span-2 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold text-slate-200">
          Recent Activity
        </h2>
        <div className="flex gap-2">
          {(['all', 'fixed', 'escalated'] as ActivityFilter[]).map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`px-3 py-1 text-xs rounded-full transition-colors ${
                filter === f
                  ? 'bg-slate-800 text-slate-400'
                  : 'text-slate-500 hover:bg-slate-800'
              }`}
            >
              {f.charAt(0).toUpperCase() + f.slice(1)}
            </button>
          ))}
        </div>
      </div>

      {/* Activity Items */}
      <div className="space-y-3">
        {filteredActivity.length === 0 ? (
          <div className="card rounded-lg p-8 text-center">
            <div className="text-slate-500">No activity found</div>
          </div>
        ) : (
          filteredActivity.slice(0, 20).map((item) => (
            <div
              key={item.id}
              className={`card rounded-lg overflow-hidden ${item.escalation_task_id ? 'border-l-2 border-rose-500' : ''}`}
            >
              <div
                className="p-4 flex items-center gap-4 cursor-pointer hover:bg-slate-800/30 transition-colors"
                onClick={() =>
                  setExpandedId(expandedId === item.id ? null : item.id)
                }
              >
                {/* Status Icon */}
                <div
                  className={`w-8 h-8 rounded-lg flex items-center justify-center ${
                    item.fixed_at
                      ? 'bg-emerald-500/20'
                      : item.escalation_task_id
                        ? 'bg-rose-500/20'
                        : 'bg-amber-500/20'
                  }`}
                >
                  {item.fixed_at ? (
                    <Check className="w-4 h-4 text-emerald-400" />
                  ) : item.escalation_task_id ? (
                    <AlertTriangle className="w-4 h-4 text-rose-400" />
                  ) : (
                    <div className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm text-slate-200 truncate">
                      {formatFilePath(item.file_path)}
                    </span>
                    <span
                      className={`px-2 py-0.5 text-xs rounded ${
                        CHECK_TYPE_COLORS[item.check_type]?.bg ??
                        'bg-slate-500/20'
                      } ${CHECK_TYPE_COLORS[item.check_type]?.text ?? 'text-slate-400'}`}
                    >
                      {item.check_type} {item.check_name ?? ''}
                    </span>
                  </div>
                  <div className="text-xs text-slate-500 mt-1">
                    {item.error_message
                      ? item.error_message.slice(0, 60) +
                        (item.error_message.length > 60 ? '...' : '')
                      : 'No error message'}
                    {item.fixed_by && ` • Fixed by ${item.fixed_by}`}
                    {item.fix_attempts > 0 &&
                      !item.fixed_at &&
                      ` • ${item.fix_attempts} attempt${item.fix_attempts > 1 ? 's' : ''}`}
                  </div>
                </div>

                {/* Time */}
                <div className="text-xs text-slate-500">
                  {formatRelativeTime(item.fixed_at ?? item.updated_at)}
                </div>

                {/* Expand Icon */}
                {item.error_message ? (
                  expandedId === item.id ? (
                    <ChevronDown className="w-4 h-4 text-slate-500" />
                  ) : (
                    <ChevronRight className="w-4 h-4 text-slate-500" />
                  )
                ) : (
                  <div className="w-4" />
                )}
              </div>

              {/* Expanded Details */}
              {expandedId === item.id && item.error_message && (
                <div className="bg-slate-950 border-t border-slate-800 p-4">
                  <div className="font-mono text-xs space-y-1">
                    <div className="text-slate-500">
                      {item.file_path}:{item.line_number ?? 0}:
                      {item.column_number ?? 0}
                    </div>
                    <div className="text-rose-400 bg-rose-500/10 px-2 py-1 rounded whitespace-pre-wrap">
                      {item.error_message}
                    </div>
                  </div>
                  {item.escalation_task_id && (
                    <div className="flex items-center gap-3 mt-3 pt-3 border-t border-slate-800">
                      <Link
                        href={`/projects/${projectId}?tab=tasks&task=${item.escalation_task_id}`}
                        className="text-xs text-rose-400 hover:text-rose-300"
                      >
                        View Escalation Task →
                      </Link>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  )
}
