interface FixPipelineCardProps {
  detected: number
  flashFixed: number
  sonnetFixed: number
  escalatedCount: number
  autoFixRate: number
}

export function FixPipelineCard({
  detected,
  flashFixed,
  sonnetFixed,
  escalatedCount,
  autoFixRate,
}: FixPipelineCardProps) {
  const unresolvedCount = Math.max(
    detected - flashFixed - sonnetFixed - escalatedCount,
    0,
  )
  const percentage = (count: number) =>
    detected > 0 ? Math.round((count / detected) * 100) : 0

  if (detected === 0) {
    return (
      <div className="card rounded-xl p-4">
        <h3 className="text-sm font-semibold text-slate-300 mb-3">
          Fix Pipeline (Last 7 Days)
        </h3>
        <div className="flex flex-col items-center justify-center py-8 text-center">
          <span className="text-slate-600 text-lg mb-2">○</span>
          <p className="text-sm text-slate-400">No quality detections this week</p>
          <p className="mt-1 text-xs text-slate-500">
            New quality findings and fix throughput will appear here automatically.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="card rounded-xl p-4">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-slate-300">
            Fix Pipeline (Last 7 Days)
          </h3>
          <p className="mt-1 text-xs text-slate-500">
            Resolution mix across automated fixes, escalations, and still-open findings.
          </p>
        </div>
        <div className="rounded-full border border-phosphor-500/20 bg-phosphor-500/10 px-2 py-1 text-2xs text-phosphor-300">
          {autoFixRate}% auto-resolved
        </div>
      </div>
      <div className="space-y-2">
        <div className="flex items-center gap-3">
          <div className="w-24 text-xs text-slate-500">Detected</div>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className="bg-slate-400 rounded-full h-2"
              style={{ width: '100%' }}
            />
          </div>
          <div className="text-xs text-slate-400 w-8 text-right tabular-nums">
            {detected}
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-24 text-xs text-slate-500">Flash Fixed</div>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className="bg-emerald-500 rounded-full h-2"
              style={{ width: `${percentage(flashFixed)}%` }}
            />
          </div>
          <div className="text-xs text-emerald-400 w-14 text-right tabular-nums">
            {flashFixed} ({percentage(flashFixed)}%)
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-24 text-xs text-slate-500">Claude Fixed</div>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className="bg-phosphor-500 rounded-full h-2"
              style={{ width: `${percentage(sonnetFixed)}%` }}
            />
          </div>
          <div className="text-xs text-phosphor-400 w-14 text-right tabular-nums">
            {sonnetFixed} ({percentage(sonnetFixed)}%)
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-24 text-xs text-slate-500">Escalated</div>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className="bg-rose-500 rounded-full h-2"
              style={{ width: `${percentage(escalatedCount)}%` }}
            />
          </div>
          <div className="text-xs text-rose-400 w-14 text-right tabular-nums">
            {escalatedCount} ({percentage(escalatedCount)}%)
          </div>
        </div>
        <div className="flex items-center gap-3">
          <div className="w-24 text-xs text-slate-500">Still Open</div>
          <div className="flex-1 bg-slate-800 rounded-full h-2">
            <div
              className="bg-slate-500 rounded-full h-2"
              style={{ width: `${percentage(unresolvedCount)}%` }}
            />
          </div>
          <div className="text-xs text-slate-400 w-14 text-right tabular-nums">
            {unresolvedCount} ({percentage(unresolvedCount)}%)
          </div>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-2 gap-2 border-t border-slate-800 pt-3 text-xs">
        <div className="rounded-lg bg-slate-950/50 px-3 py-2 text-slate-400">
          Automated
          <div className="mt-1 text-sm font-medium text-slate-200">
            {flashFixed + sonnetFixed}
          </div>
        </div>
        <div className="rounded-lg bg-slate-950/50 px-3 py-2 text-slate-400">
          Manual Follow-up
          <div className="mt-1 text-sm font-medium text-slate-200">
            {escalatedCount + unresolvedCount}
          </div>
        </div>
      </div>
    </div>
  )
}
