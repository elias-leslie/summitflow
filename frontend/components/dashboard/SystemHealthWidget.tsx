'use client'

import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSystemStats } from '@/hooks/useSystemStats'

interface SystemHealthWidgetProps {
  className?: string
}

const STATUS_COLORS = {
  ok: { bar: 'bg-neon-cyan', text: 'text-neon-cyan' },
  warning: { bar: 'bg-amber-400', text: 'text-amber-400' },
  critical: { bar: 'bg-rose-500', text: 'text-rose-500' },
} as const

export function SystemHealthWidget({ className }: SystemHealthWidgetProps) {
  const { data, isLoading, error, refetch, isFetching } = useSystemStats()

  if (isLoading) {
    return (
      <div className={cn('flex items-center gap-2 text-xs text-slate-500', className)}>
        <div className="w-3 h-3 border border-slate-600 border-t-phosphor-500 rounded-full animate-spin" />
        <span>Loading metrics...</span>
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className={cn('flex items-center gap-2 text-xs text-slate-500', className)}>
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
    <div className={cn('flex items-center gap-4', className)}>
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500 w-7">{m.label}</span>
          <div className="w-14 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all duration-700', STATUS_COLORS[m.status].bar)}
              style={{ width: `${Math.min(m.percent, 100)}%` }}
            />
          </div>
          <span className={cn('text-[11px] font-mono tabular-nums w-8', STATUS_COLORS[m.status].text)}>
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
        <RefreshCw className={cn('w-3 h-3', isFetching && 'animate-spin')} />
      </button>
    </div>
  )
}
