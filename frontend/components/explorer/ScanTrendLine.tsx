/**
 * ScanTrendLine - Minimal sparkline for scan history
 *
 * Architecture: SVG for trend line, HTML/CSS for event markers
 * Time-based positioning with dynamic window sizing
 */

'use client'

import { useMemo, useState } from 'react'
import { useScanHistory } from '@/lib/hooks/useScanHistory'
import { cn } from '@/lib/utils'
import { ScanEventMarker } from './ScanEventMarker'
import { ScanTooltip } from './ScanTooltip'
import { ScanTrendSvg } from './ScanTrendSvg'
import { calculateTimeWindow, getTimePosition } from './ScanTrendUtils'

interface ScanTrendLineProps {
  projectId: string
  className?: string
}

interface ProcessedScan {
  id: number
  started_at: string
  triggered_by: string
  metrics: Record<string, unknown>
  complexity: number | null
  delta: string
  xPosition: number
}

function buildSvgPaths(chartData: ProcessedScan[] | null): {
  linePath: string
  areaPath: string
} {
  if (!chartData) return { linePath: '', areaPath: '' }

  const points = chartData
    .filter((d) => d.complexity !== null)
    .map((d) => ({ x: d.xPosition, y: d.complexity as number }))

  if (points.length < 2) return { linePath: '', areaPath: '' }

  const minY = Math.min(...points.map((p) => p.y)) * 0.95
  const maxY = Math.max(...points.map((p) => p.y)) * 1.05
  const range = maxY - minY || 1

  const scaled = points.map((p) => ({
    x: p.x,
    y: 100 - ((p.y - minY) / range) * 100,
  }))

  let line = `M ${scaled[0].x} ${scaled[0].y}`
  let area = `M ${scaled[0].x} 100 L ${scaled[0].x} ${scaled[0].y}`

  for (let i = 1; i < scaled.length; i++) {
    const cpx = (scaled[i - 1].x + scaled[i].x) / 2
    line += ` C ${cpx} ${scaled[i - 1].y}, ${cpx} ${scaled[i].y}, ${scaled[i].x} ${scaled[i].y}`
    area += ` C ${cpx} ${scaled[i - 1].y}, ${cpx} ${scaled[i].y}, ${scaled[i].x} ${scaled[i].y}`
  }

  area += ` L ${scaled[scaled.length - 1].x} 100 Z`
  return { linePath: line, areaPath: area }
}

function processScans(
  scans: Array<{
    id: number
    started_at: string
    triggered_by: string
    metrics: Record<string, unknown>
  }>,
  timeWindow: { start: number; end: number },
): ProcessedScan[] {
  const sorted = [...scans].sort(
    (a, b) =>
      new Date(a.started_at).getTime() - new Date(b.started_at).getTime(),
  )

  return sorted.map((scan, idx, arr): ProcessedScan => {
    const curr =
      typeof scan.metrics?.complexity === 'number'
        ? scan.metrics.complexity
        : null
    const prev =
      idx > 0 && typeof arr[idx - 1].metrics?.complexity === 'number'
        ? (arr[idx - 1].metrics.complexity as number)
        : null

    let delta = '—'
    if (curr !== null && prev !== null) {
      const diff = curr - prev
      delta =
        diff > 0 ? `+${diff.toFixed(0)}` : diff < 0 ? diff.toFixed(0) : '±0'
    }

    return {
      id: scan.id,
      started_at: scan.started_at,
      triggered_by: scan.triggered_by,
      metrics: scan.metrics,
      complexity: curr,
      delta,
      xPosition: getTimePosition(
        new Date(scan.started_at).getTime(),
        timeWindow.start,
        timeWindow.end,
      ),
    }
  })
}

export function ScanTrendLine({ projectId, className }: ScanTrendLineProps) {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
  const { scans, isLoading, isError } = useScanHistory({ projectId, days: 30 })

  const timeWindow = useMemo(() => {
    if (!scans || scans.length === 0) return null
    return calculateTimeWindow(scans)
  }, [scans])

  const chartData = useMemo((): ProcessedScan[] | null => {
    if (!scans || scans.length === 0 || !timeWindow) return null
    return processScans(scans, timeWindow)
  }, [scans, timeWindow])

  const hasComplexityData =
    chartData?.some((d) => d.complexity !== null) ?? false

  const { linePath, areaPath } = useMemo(
    () => buildSvgPaths(chartData),
    [chartData],
  )

  if (isLoading) {
    return (
      <div className={cn('h-12 flex items-center justify-center', className)}>
        <div className="h-px w-20 bg-gradient-to-r from-transparent via-slate-600 to-transparent animate-pulse" />
      </div>
    )
  }

  if (isError || !chartData || chartData.length === 0) {
    return (
      <div className={cn('h-12 flex items-center justify-center', className)}>
        <span className="text-[10px] font-mono text-slate-600">
          No scan activity
        </span>
      </div>
    )
  }

  const hovered = hoveredIndex !== null ? chartData[hoveredIndex] : null

  return (
    <div
      className={cn('h-12 relative', className)}
      data-testid="scan-trend-line"
    >
      {hasComplexityData && linePath && (
        <ScanTrendSvg linePath={linePath} areaPath={areaPath} />
      )}

      {!hasComplexityData && (
        <div
          className="absolute left-0 right-0 h-px bg-slate-700/50"
          style={{ top: '50%' }}
        />
      )}

      <div className="absolute inset-x-0 top-0 h-4 flex items-center">
        {chartData.map((scan, i) => (
          <ScanEventMarker
            key={scan.id}
            scanId={scan.id}
            xPosition={scan.xPosition}
            triggeredBy={scan.triggered_by}
            isHovered={hoveredIndex === i}
            onMouseEnter={() => setHoveredIndex(i)}
            onMouseLeave={() => setHoveredIndex(null)}
          />
        ))}
      </div>

      {hovered && <ScanTooltip scan={hovered} />}
    </div>
  )
}
