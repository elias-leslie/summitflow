import type { CheckResult } from './HealthTypes'
import {
  formatCheckLabel,
  formatFilePath,
  formatIssueStatus,
} from './HealthUtils'
import { formatTimeAgo } from '@/lib/format'

interface NeedsAttentionCardProps {
  items: CheckResult[]
  hasChecks?: boolean
  totalUnfixed?: number
}

export function NeedsAttentionCard({
  items,
  hasChecks = true,
  totalUnfixed = items.length,
}: NeedsAttentionCardProps) {
  if (items.length === 0) {
    return (
      <div className="card rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className={hasChecks ? 'text-emerald-500' : 'text-slate-500'}>
            {hasChecks ? '✓' : '○'}
          </span>
          {hasChecks ? 'All Clear' : 'No Findings Yet'}
        </h3>
        <p className="text-xs text-slate-500">
          {hasChecks
            ? 'No unresolved quality issues need attention right now.'
            : 'Quality findings will appear here after the first recorded check run.'}
        </p>
      </div>
    )
  }

  const visibleItems = items
    .slice()
    .sort((left, right) => {
      if (left.escalation_task_id && !right.escalation_task_id) return -1
      if (!left.escalation_task_id && right.escalation_task_id) return 1
      if (left.error_count !== right.error_count) return right.error_count - left.error_count
      return right.created_at.localeCompare(left.created_at)
    })
    .slice(0, 5)
  const escalatedCount = items.filter((item) => item.escalation_task_id).length

  return (
    <div className="card rounded-xl p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-300 flex items-center gap-2">
            <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
            Needs Attention
            <span className="text-xs text-slate-500 font-normal">
              ({totalUnfixed})
            </span>
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Escalated issues are shown first, followed by the most severe open findings.
          </p>
        </div>
        {escalatedCount > 0 && (
          <span className="rounded-full border border-rose-500/30 bg-rose-500/10 px-2 py-1 text-2xs text-rose-300">
            {escalatedCount} escalated
          </span>
        )}
      </div>
      <div className="space-y-2">
        {visibleItems.map((item) => (
          <div
            key={item.id}
            className="flex items-start justify-between gap-4 py-2 border-b border-slate-800 last:border-0"
          >
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <div className="text-xs font-medium text-slate-200">
                  {formatCheckLabel(item.check_type, item.check_name)}
                </div>
                <div
                  className="font-mono text-xs text-slate-400 truncate"
                  title={item.file_path ?? 'Unknown file'}
                >
                  {formatFilePath(item.file_path)}
                </div>
              </div>
              <div className="text-xs text-slate-500">
                {item.line_number ? `Line ${item.line_number} · ` : ''}
                {item.error_count} error{item.error_count === 1 ? '' : 's'}
                {item.warning_count > 0
                  ? ` · ${item.warning_count} warning${item.warning_count === 1 ? '' : 's'}`
                  : ''}
                {' · '}
                {formatTimeAgo(item.created_at, 'Unknown time')}
              </div>
            </div>
            <span
              className={`text-xs shrink-0 ${
                item.escalation_task_id ? 'text-rose-300' : 'text-purple-400'
              }`}
              title={item.escalation_task_id ? `Escalated to ${item.escalation_task_id}` : undefined}
            >
              {formatIssueStatus(item)}
            </span>
          </div>
        ))}
      </div>
      {items.length > 5 && (
        <div className="mt-3 pt-3 border-t border-slate-800 text-xs text-slate-500">
          +{items.length - 5} more unresolved issues
        </div>
      )}
    </div>
  )
}
