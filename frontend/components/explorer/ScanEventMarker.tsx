/**
 * ScanEventMarker - Individual event marker for scan timeline
 */

'use client'

import { cn } from '@/lib/utils'
import { getTriggerColor } from './ScanTrendConstants'

interface ScanEventMarkerProps {
  scanId: number
  xPosition: number
  triggeredBy: string
  isHovered: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
}

export function ScanEventMarker({
  scanId,
  xPosition,
  triggeredBy,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: ScanEventMarkerProps) {
  const color = getTriggerColor(triggeredBy)

  return (
    <div
      key={scanId}
      className="absolute -translate-x-1/2"
      style={{ left: `${xPosition}%` }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div
        className={cn(
          'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 rounded-full transition-all duration-200',
          isHovered ? 'w-3 h-3 opacity-40' : 'w-2 h-2 opacity-0',
        )}
        style={{ backgroundColor: color, filter: 'blur(3px)' }}
      />
      <div
        className={cn(
          'relative rounded-full cursor-pointer transition-all duration-150',
          isHovered ? 'w-2 h-2' : 'w-1.5 h-1.5',
        )}
        style={{
          backgroundColor: color,
          boxShadow: isHovered ? `0 0 8px ${color}` : `0 0 4px ${color}50`,
        }}
      />
    </div>
  )
}
