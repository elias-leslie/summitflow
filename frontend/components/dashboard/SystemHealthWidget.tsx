'use client'

import { RefreshCw } from 'lucide-react'
import clsx from 'clsx'
import { useSystemStats } from '@/hooks/useSystemStats'

interface SystemHealthWidgetProps {
  className?: string
}

const STATUS_COLORS = {
  ok: { bar: 'bg-neon-cyan', text: 'text-neon-cyan', glow: '0 0 8px rgba(0, 245, 255, 0.3)' },
  warning: { bar: 'bg-amber-400', text: 'text-amber-400', glow: '0 0 8px rgba(251, 191, 36, 0.3)' },
  critical: { bar: 'bg-rose-500', text: 'text-rose-500', glow: '0 0 8px rgba(244, 63, 94, 0.3)' },
} as const

export function SystemHealthWidget({ className }: SystemHealthWidgetProps) {
  const { data, isLoading, error, refetch, isFetching } = useSystemStats()

  if (isLoading) {
    return (
      <div className={clsx('space-y-3', className)}>
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="h-3 w-3 rounded-full border border-slate-600 border-t-phosphor-500 animate-spin" />
          <span>Loading live metrics...</span>
        </div>
        <div className="grid gap-3">
          {Array.from({ length: 3 }).map((_, index) => (
            <div
              key={index}
              className="animate-pulse rounded-2xl border border-slate-800/70 bg-slate-900/70 p-4"
            >
              <div className="h-3 w-16 rounded bg-slate-800" />
              <div className="mt-3 h-2 rounded-full bg-slate-800" />
            </div>
          ))}
        </div>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className={clsx('rounded-2xl border border-rose-500/20 bg-rose-500/8 p-4', className)}>
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="eyebrow">System load</div>
            <p className="mt-2 text-sm text-rose-300">Metrics unavailable</p>
            <p className="mt-1 text-xs text-slate-500">
              The monitor endpoint did not return a usable payload.
            </p>
          </div>
          <button
            type="button"
            onClick={() => refetch()}
            className="rounded-full border border-rose-500/20 bg-rose-500/10 p-2 text-rose-300 transition-colors hover:bg-rose-500/16"
            aria-label="Retry loading metrics"
          >
            <RefreshCw className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
    )
  }

  const metrics = [
    { label: 'CPU', percent: data.cpu.percent_used, status: data.cpu.status },
    { label: 'RAM', percent: data.memory.percent_used, status: data.memory.status },
    { label: 'Disk', percent: data.disk.percent_used, status: data.disk.status },
  ] as const

  return (
    <div className={clsx('space-y-3', className)}>
      <div className="grid gap-3">
        {metrics.map((m) => (
          <div
            key={m.label}
            className="rounded-lg border border-slate-800/70 bg-slate-950/55 px-3 py-2"
            title={`${m.label}: ${m.percent}%`}
          >
            <div className="flex items-center justify-between gap-2">
              <span className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-500">{m.label}</span>
              <span className={clsx('font-mono text-sm font-bold tabular-nums', STATUS_COLORS[m.status].text)}>
                {m.percent}%
              </span>
            </div>
            <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-800 ring-1 ring-white/[0.04]">
              <div
                className={clsx('h-full rounded-full transition-all duration-700', STATUS_COLORS[m.status].bar)}
                style={{
                  width: `${Math.min(m.percent, 100)}%`,
                  boxShadow: STATUS_COLORS[m.status].glow,
                }}
              />
            </div>
          </div>
        ))}
      </div>
      <div className="flex items-center justify-between rounded-lg border border-slate-800/70 bg-slate-950/45 px-3 py-2 text-xs text-slate-500">
        <span>Auto-refreshing</span>
        <button
          type="button"
          onClick={() => refetch()}
          disabled={isFetching}
          className="inline-flex items-center gap-1.5 rounded-full border border-slate-700/60 bg-slate-900/70 px-3 py-1.5 text-slate-300 transition-colors hover:border-slate-600 hover:text-slate-100"
          aria-label="Refresh system status"
        >
          <RefreshCw className={clsx('h-3 w-3', isFetching && 'animate-spin')} />
          Refresh
        </button>
      </div>
    </div>
  )
}
