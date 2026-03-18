'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { type RuntimeModeStatus, runtimeApi } from '@/lib/api/runtime'

const runtimeBadge: Record<string, string> = {
  hybrid: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  native: 'border-sky-500/30 bg-sky-500/10 text-sky-300',
  docker: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  'docker-stopped': 'border-slate-500/30 bg-slate-500/10 text-slate-400',
}

function runtimeSummary(rt: RuntimeModeStatus): string {
  if (rt.runtime === 'hybrid')
    return 'Native apps + Docker infra (PostgreSQL, Redis, Hatchet)'
  if (rt.runtime === 'native')
    return 'All services running natively, no Docker app containers'
  if (rt.runtime === 'docker')
    return `Full Docker stack in ${rt.current_mode} mode`
  return 'Docker stack stopped — saved preference controls next run'
}

export function RuntimeModeBanner() {
  const { data: rt, error, isLoading } = useQuery({
    queryKey: ['runtime', 'mode'],
    queryFn: runtimeApi.getRuntime,
    refetchInterval: 10_000,
  })

  if (isLoading) {
    return <div className="h-10 animate-pulse rounded-lg bg-slate-800/40" />
  }

  if (error || !rt) {
    return (
      <div className="rounded-lg border border-red-500/30 bg-red-950/20 px-4 py-2.5 text-sm text-red-300">
        {error instanceof Error ? error.message : 'Runtime mode unavailable'}
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-700/60 bg-slate-900/70 px-4 py-2.5">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        {/* Badge */}
        <span
          className={clsx(
            'inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.14em]',
            runtimeBadge[rt.runtime] ?? runtimeBadge['docker-stopped'],
          )}
        >
          {rt.runtime}
        </span>

        {/* Summary */}
        <span className="text-sm text-slate-400 flex-1 min-w-0">
          {runtimeSummary(rt)}
        </span>

        {/* Inline metadata */}
        <div className="hidden md:flex items-center gap-3 text-xs text-slate-500">
          <span>Apps: <span className="text-slate-300">{rt.apps_runtime}</span></span>
          <span>Infra: <span className="text-slate-300">{rt.infra_runtime}</span></span>
        </div>
      </div>
    </div>
  )
}
