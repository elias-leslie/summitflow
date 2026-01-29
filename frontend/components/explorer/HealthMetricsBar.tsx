/**
 * HealthMetricsBar - Displays code health metrics with visual bars
 */

'use client'

import { cn } from '@/lib/utils'

interface HealthMetricsBarProps {
  highCount: number
  mediumCount: number
  totalComplexity: number
  isLoading: boolean
}

export function HealthMetricsBar({
  highCount,
  mediumCount,
  totalComplexity,
  isLoading,
}: HealthMetricsBarProps) {
  const total = highCount + mediumCount

  return (
    <div className="grid grid-cols-3 gap-3">
      {/* Critical metric */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">CRITICAL</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-red-400 tabular-nums">
            {isLoading ? '-' : highCount}
          </span>
          <span className="text-xs text-slate-500">files</span>
        </div>
        <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
          <div
            className="h-full bg-red-500 transition-all duration-500"
            style={{
              width: total > 0 ? `${(highCount / total) * 100}%` : '0%',
            }}
          />
        </div>
      </div>

      {/* Warning metric */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">WARNING</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-amber-400 tabular-nums">
            {isLoading ? '-' : mediumCount}
          </span>
          <span className="text-xs text-slate-500">files</span>
        </div>
        <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
          <div
            className="h-full bg-amber-500 transition-all duration-500"
            style={{
              width: total > 0 ? `${(mediumCount / total) * 100}%` : '0%',
            }}
          />
        </div>
      </div>

      {/* Complexity Gauge */}
      <div className="p-3 rounded bg-slate-800/50 border border-slate-700/50">
        <div className="text-xs text-slate-500 mb-1">TOTAL COMPLEXITY</div>
        <div className="flex items-baseline gap-2">
          <span className="text-2xl font-bold text-emerald-400 tabular-nums">
            {isLoading ? '-' : Math.round(totalComplexity)}
          </span>
          <span className="text-xs text-slate-500">score</span>
        </div>
        <ComplexityGauge value={totalComplexity} max={5000} />
      </div>
    </div>
  )
}

function ComplexityGauge({ value, max }: { value: number; max: number }) {
  const percentage = Math.min((value / max) * 100, 100)
  const color =
    percentage > 75
      ? 'bg-red-500'
      : percentage > 50
        ? 'bg-amber-500'
        : 'bg-emerald-500'

  return (
    <div className="mt-2 h-1 rounded-full bg-slate-700/50 overflow-hidden">
      <div
        className={cn('h-full transition-all duration-500', color)}
        style={{ width: `${percentage}%` }}
      />
    </div>
  )
}
