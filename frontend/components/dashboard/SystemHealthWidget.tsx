'use client'

import { RefreshCw } from 'lucide-react'
import { cn } from '@/lib/utils'
import { useSystemStats } from '@/hooks/useSystemStats'

interface SystemHealthWidgetProps {
  className?: string
}

function getBarColor(status: 'ok' | 'warning' | 'critical'): string {
  switch (status) {
    case 'ok':
      return 'bg-neon-cyan'
    case 'warning':
      return 'bg-amber-400'
    case 'critical':
      return 'bg-rose-500'
  }
}

function getTextColor(status: 'ok' | 'warning' | 'critical'): string {
  switch (status) {
    case 'ok':
      return 'text-neon-cyan'
    case 'warning':
      return 'text-amber-400'
    case 'critical':
      return 'text-rose-500'
  }
}

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
    { label: 'CPU', percent: data.cpu.percent_used, status: data.cpu.status, detail: `${data.cpu.cores}c` },
    { label: 'RAM', percent: data.memory.percent_used, status: data.memory.status, detail: `${data.memory.used_gb.toFixed(0)}/${data.memory.total_gb.toFixed(0)}G` },
    { label: 'Disk', percent: data.disk.percent_used, status: data.disk.status, detail: `${data.disk.used_gb.toFixed(0)}/${data.disk.total_gb.toFixed(0)}G` },
  ] as const

  return (
    <div className={cn('flex items-center gap-4', className)}>
      {metrics.map((m) => (
        <div key={m.label} className="flex items-center gap-2">
          <span className="text-[11px] text-slate-500 w-7">{m.label}</span>
          <div className="w-14 h-1.5 bg-slate-800 rounded-full overflow-hidden">
            <div
              className={cn('h-full rounded-full transition-all duration-700', getBarColor(m.status))}
              style={{ width: `${Math.min(m.percent, 100)}%` }}
            />
          </div>
          <span className={cn('text-[11px] font-mono tabular-nums w-8', getTextColor(m.status))}>
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
