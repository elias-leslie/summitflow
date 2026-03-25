'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { Activity, Boxes, DatabaseZap, Layers3 } from 'lucide-react'
import { type RuntimeModeStatus, runtimeApi } from '@/lib/api/runtime'
import { POLL_MONITOR } from '@/lib/polling'

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
    refetchInterval: POLL_MONITOR,
  })

  if (isLoading) {
    return <div className="h-32 animate-pulse rounded-3xl bg-slate-800/40" />
  }

  if (error || !rt) {
    return (
      <div className="rounded-3xl border border-red-500/30 bg-red-950/20 px-5 py-4 text-sm text-red-300">
        {error instanceof Error ? error.message : 'Runtime mode unavailable'}
      </div>
    )
  }

  const details = [
    {
      label: 'Apps',
      value: rt.apps_runtime,
      icon: Activity,
      tone: 'border-cyan-500/20 bg-cyan-500/10 text-cyan-200',
    },
    {
      label: 'Infra',
      value: rt.infra_runtime,
      icon: DatabaseZap,
      tone: 'border-emerald-500/20 bg-emerald-500/10 text-emerald-200',
    },
    {
      label: 'Mode',
      value: `${rt.current_mode} now`,
      icon: Layers3,
      tone: 'border-amber-500/20 bg-amber-500/10 text-amber-200',
    },
    {
      label: 'Source',
      value: rt.source,
      icon: Boxes,
      tone: 'border-slate-700/70 bg-slate-950/70 text-slate-200',
    },
  ]

  return (
    <div className="card-elevated px-5 py-5">
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="eyebrow">Runtime posture</div>
          <h2 className="display mt-2 text-2xl font-semibold text-slate-50">
            {rt.runtime === 'hybrid'
              ? 'Hybrid operations'
              : rt.runtime === 'native'
                ? 'Native operations'
                : rt.runtime === 'docker'
                  ? 'Docker operations'
                  : 'Standby posture'}
          </h2>
          <p className="mt-2 text-sm leading-relaxed text-slate-300">
            {runtimeSummary(rt)}
          </p>
        </div>
        <span
          className={clsx(
            'inline-flex items-center rounded-full border px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.18em]',
            runtimeBadge[rt.runtime] ?? runtimeBadge['docker-stopped'],
          )}
        >
          {rt.runtime}
        </span>
      </div>

      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        {details.map((detail) => {
          const Icon = detail.icon
          return (
            <div
              key={detail.label}
              className={clsx(
                'rounded-2xl border px-4 py-3 transition-colors',
                detail.tone,
              )}
            >
              <div className="flex items-center gap-2 text-[11px] uppercase tracking-[0.18em] text-slate-400">
                <Icon className="h-3.5 w-3.5 text-current" />
                {detail.label}
              </div>
              <div className="mt-2 text-sm font-medium capitalize text-slate-100">
                {detail.value}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
