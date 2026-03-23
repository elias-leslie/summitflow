'use client'

import { Badge } from '@/components/ui/badge'
import type { HealthSummary } from './HealthTypes'
import {
  formatCheckLabel,
  formatLastRun,
  getHealthCheckState,
} from './HealthUtils'

interface QualityGateStatusProps {
  health: HealthSummary | undefined
}

export function QualityGateStatus({ health }: QualityGateStatusProps) {
  const checks = health?.checks

  if (!checks || Object.keys(checks).length === 0) {
    return (
      <div className="card rounded-xl px-4 py-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-slate-300 display">
              Quality Gates
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              No quality runs have been recorded for this project yet.
            </p>
          </div>
          <Badge variant="slate">No data</Badge>
        </div>
      </div>
    )
  }

  const entries = Object.entries(checks).sort(([, left], [, right]) => {
    const leftScore =
      (left.status === 'pass' || left.status === 'passing' ? 0 : 10) +
      (left.warning_count > 0 ? 1 : 0)
    const rightScore =
      (right.status === 'pass' || right.status === 'passing' ? 0 : 10) +
      (right.warning_count > 0 ? 1 : 0)

    return rightScore - leftScore
  })

  const latestRun = entries
    .map(([, check]) => check.last_run)
    .filter(Boolean)
    .sort()
    .at(-1)

  return (
    <div className="card rounded-xl px-4 py-3">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h3 className="text-sm font-semibold text-slate-300 display">
              Quality Gates
            </h3>
            <Badge variant={health?.overall_pass ? 'phosphor' : 'rose'}>
              {health?.overall_pass ? 'Passing' : 'Failing'}
            </Badge>
            <Badge variant={health?.total_unfixed ? 'amber' : 'slate'}>
              {health?.total_unfixed ?? 0} open
            </Badge>
          </div>
          <p className="mt-1 text-xs text-slate-500">
            Last run {formatLastRun(latestRun)}
          </p>
        </div>
        <div className="grid flex-1 grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
          {entries.map(([name, check]) => {
            const state = getHealthCheckState(check)

            return (
              <div
                key={name}
                className="rounded-lg border border-slate-800 bg-slate-950/40 px-3 py-2.5 transition-colors hover:border-slate-700"
              >
                <div className="flex items-center justify-between gap-2">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className={`h-2 w-2 rounded-full ${state.dotColor} ring-2 ring-slate-900`} />
                    <span className={`truncate text-xs font-medium ${state.textColor}`}>
                      {formatCheckLabel(name)}
                    </span>
                  </div>
                  <span className="text-2xs text-slate-500 tabular-nums font-medium">
                    {state.badgeLabel}
                  </span>
                </div>
                <div className="mt-1.5 text-2xs text-slate-600">
                  {formatLastRun(check.last_run)}
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}
