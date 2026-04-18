/**
 * ScanTooltip - Hover tooltip for scan details
 */

'use client'

import { cn } from '@/lib/utils'
import { getTriggerColor, getTriggerLabel } from './ScanTrendConstants'
import { formatDate } from './ScanTrendUtils'

interface ProcessedScan {
  id: number
  started_at: string
  triggered_by: string
  complexity: number | null
  delta: string
  xPosition: number
}

interface ScanTooltipProps {
  scan: ProcessedScan
}

export function ScanTooltip({ scan }: ScanTooltipProps) {
  const color = getTriggerColor(scan.triggered_by)

  return (
    <div
      className="absolute z-50 pointer-events-none"
      style={{
        left: `${scan.xPosition}%`,
        top: 0,
        transform: `translateX(${scan.xPosition > 75 ? '-100%' : scan.xPosition < 25 ? '0%' : '-50%'}) translateY(-100%)`,
        paddingBottom: '8px',
      }}
    >
      <div
        className="bg-slate-900/95 backdrop-blur-sm border rounded px-2 py-1.5 shadow-xl whitespace-nowrap"
        style={{
          borderColor: `${color}40`,
        }}
      >
        <div className="flex items-center gap-1.5 mb-0.5">
          <div
            className="w-1.5 h-1.5 rounded-full"
            style={{
              backgroundColor: color,
              boxShadow: `0 0 4px ${color}`,
            }}
          />
          <span className="text-[10px] font-mono text-slate-200">
            {getTriggerLabel(scan.triggered_by)}
          </span>
        </div>
        <div className="text-[9px] font-mono text-slate-500">
          {formatDate(scan.started_at)}
        </div>
        {scan.complexity !== null && (
          <div className="flex items-center gap-1.5 mt-1 pt-1 border-t border-slate-700/50 text-[9px] font-mono">
            <span className="text-slate-400">{scan.complexity.toFixed(0)}</span>
            <span
              className={cn(
                scan.delta.startsWith('+') && 'text-rose-400',
                scan.delta.startsWith('-') && 'text-emerald-400',
                (scan.delta === '±0' || scan.delta === '—') && 'text-slate-500',
              )}
            >
              {scan.delta}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
