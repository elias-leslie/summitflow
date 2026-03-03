'use client'

import type { HealthSummary } from './HealthTypes'

interface QualityGateStatusProps {
  checks: HealthSummary['checks'] | undefined
}

function CheckBadge({
  name,
  check,
}: {
  name: string
  check: { status: string; error_count: number; warning_count: number }
}) {
  const isPassing = check.status === 'pass' || check.status === 'passing'
  const hasWarnings = check.warning_count > 0
  const errorCount = check.error_count

  const dotColor = isPassing
    ? hasWarnings
      ? 'bg-amber-500'
      : 'bg-emerald-500'
    : 'bg-rose-500'

  const textColor = isPassing
    ? hasWarnings
      ? 'text-amber-400'
      : 'text-slate-400'
    : 'text-rose-400'

  return (
    <div className="flex items-center gap-1.5">
      <span className={`w-1.5 h-1.5 rounded-full ${dotColor}`} />
      <span className={`text-xs ${textColor}`}>{name}</span>
      {!isPassing && errorCount > 0 && (
        <span className="text-xs text-rose-400/70 tabular-nums">
          ({errorCount})
        </span>
      )}
      {isPassing && hasWarnings && (
        <span className="text-xs text-amber-400/70 tabular-nums">
          ({check.warning_count})
        </span>
      )}
    </div>
  )
}

export function QualityGateStatus({ checks }: QualityGateStatusProps) {
  if (!checks || Object.keys(checks).length === 0) {
    return (
      <div className="card rounded-xl px-4 py-3">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-slate-300">
            Quality Gates
          </h3>
          <span className="text-xs text-slate-500">No checks configured</span>
        </div>
      </div>
    )
  }

  return (
    <div className="card rounded-xl px-4 py-3">
      <div className="flex items-center gap-4">
        <h3 className="text-sm font-semibold text-slate-300">Quality Gates</h3>
        <div className="flex items-center gap-4">
          {Object.entries(checks).map(([name, check]) => (
            <CheckBadge key={name} name={name} check={check} />
          ))}
        </div>
      </div>
    </div>
  )
}
