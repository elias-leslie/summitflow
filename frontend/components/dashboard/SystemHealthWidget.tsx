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
      <div className={clsx('flex items-center gap-2 text-xs text-slate-500', className)}>
        <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
        <span>Loading metrics...</span>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className={clsx('flex items-center gap-2 text-xs text-slate-500', className)}>
        <span className="text-rose-400/80">Metrics unavailable</span>
        <button
          type="button"
          onClick={() => refetch()}
          className="p-0.5 text-slate-600 hover:text-slate-400 transition-colors"
          aria-label="Retry loading metrics"
        >
          <RefreshCw className="w-3 h-3" />
        </button>
      </div>
    )
  }

  const metrics = [
    { label: 'CPU', percent: data.cpu.percent_used, status: data.cpu.status },
    { label: 'RAM', percent: data.memory.percent_used, status: data.memory.status },
    { label: 'Disk', percent: data.disk.percent_used, status: data.disk.status },
  ] as const

  return (
    <div className={clsx('flex items-center gap-4', className)}>
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center gap-2" title={`${m.label}: ${m.percent}%`}>
          <span className="text-2xs text-slate-500 w-8 font-medium tracking-wide">{m.label}</span>
          <div className="w-24 h-2 bg-slate-800 rounded-full overflow-hidden ring-1 ring-white/[0.03]">
            <div
              className={clsx('h-full rounded-full transition-all duration-700', STATUS_COLORS[m.status].bar)}
              style={{ width: `${Math.min(m.percent, 100)}%`, boxShadow: STATUS_COLORS[m.status].glow }}
            />
          </div>
          <span className={clsx('text-2xs font-mono tabular-nums w-9', STATUS_COLORS[m.status].text)}>
            {m.percent}%
          </span>
        </div>
      ))}
      <button
        type="button"
        onClick={() => refetch()}
        disabled={isFetching}
        className="p-1 rounded text-slate-600 hover:text-slate-400 transition-colors"
        aria-label="Refresh system status"
      >
        <RefreshCw className={clsx('w-3 h-3', isFetching && 'animate-spin')} />
      </button>
    </div>
  )
}
