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
      </h3>
      <div className="space-y-2">
        {items.slice(0, 5).map((item) => (
          <div
            key={item.id}
            className="flex items-center justify-between py-2 border-b border-slate-800 last:border-0"
          >
            <div>
              <div className="font-mono text-xs text-slate-300 truncate max-w-[140px]">
                {formatFilePath(item.file_path)}
              </div>
              <div className="text-xs text-slate-500">{item.check_type} error</div>
            </div>
            <span className="text-xs text-purple-400">
              {item.fix_attempts > 0 ? `${item.fix_attempts} tries` : 'Pending'}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}
