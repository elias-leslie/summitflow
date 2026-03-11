import type { CheckResult } from './HealthTypes'
import { formatFilePath } from './HealthUtils'

interface NeedsAttentionCardProps {
  items: CheckResult[]
}

export function NeedsAttentionCard({ items }: NeedsAttentionCardProps) {
  if (items.length === 0) {
    return (
      <div className="card rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
          <span className="text-emerald-500">✓</span>
          All Clear
        </h3>
        <p className="text-xs text-slate-500">
          All quality checks passing — no issues need attention.
        </p>
      </div>
    )
  }

  return (
    <div className="card rounded-xl p-4">
      <h3 className="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
        <span className="w-2 h-2 bg-amber-500 rounded-full animate-pulse" />
        Needs Attention
        <span className="text-xs text-slate-500 font-normal">({items.length})</span>
      </h3>
      <div className="space-y-2">
        {items.slice(0, 5).map((item) => (
          <div
            key={item.id}
            className="flex items-start justify-between gap-4 py-2 border-b border-slate-800 last:border-0"
          >
            <div className="min-w-0">
              <div
                className="font-mono text-xs text-slate-300 truncate"
                title={item.file_path ?? 'Unknown file'}
              >
                {formatFilePath(item.file_path)}
              </div>
              <div className="text-xs text-slate-500">
                {item.check_type}
                {item.line_number ? `:${item.line_number}` : ''} • {item.error_count} errors
              </div>
            </div>
            <span
              className="text-xs text-purple-400 shrink-0"
              title={item.escalation_task_id ? `Escalated to ${item.escalation_task_id}` : undefined}
            >
              {item.escalation_task_id
                ? 'Escalated'
                : item.fix_attempts > 0
                  ? `${item.fix_attempts} tries`
                  : 'Pending'}
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
