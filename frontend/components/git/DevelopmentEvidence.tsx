import type { DevelopmentEvidence as Evidence } from '@/lib/api/git'

export function evidenceTime(value: Evidence['observed_at']): string {
  if (value === null) return 'Time unavailable'
  const date = new Date(typeof value === 'number' ? value * 1000 : value)
  return Number.isNaN(date.getTime())
    ? 'Time unavailable'
    : date.toLocaleString()
}

export function DevelopmentEvidence({
  label,
  evidence,
}: {
  label: string
  evidence: Evidence
}) {
  const failed = ['failed', 'error'].includes(evidence.state)
  return (
    <div className="min-w-0 space-y-1">
      <dt className="text-xs font-medium text-slate-300">{label}</dt>
      <dd
        className={failed ? 'text-sm text-rose-300' : 'text-sm text-slate-100'}
      >
        {evidence.state.replaceAll('_', ' ')}
        {evidence.drift && (
          <span className="ml-2 text-xs text-amber-300">Source drift</span>
        )}
      </dd>
      {evidence.source_commit && (
        <dd className="break-all font-mono text-xs text-slate-300">
          {evidence.source_commit}
        </dd>
      )}
      <dd className="text-xs text-slate-400">{evidence.reason}</dd>
      {evidence.observed_at !== null && (
        <dd className="text-xs text-slate-400">
          {evidenceTime(evidence.observed_at)}
        </dd>
      )}
    </div>
  )
}
