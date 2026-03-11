/**
 * SummaryBar - Horizontal metrics strip
 *
 * Displays key stats in a scannable horizontal bar.
 * Clicking any metric acts as a quick filter.
 */

'use client'

import { Clock, Loader2, RefreshCw } from 'lucide-react'
import { useEffect, useState } from 'react'
import { formatDate, formatTimeAgo } from '@/lib/format'
import { cn } from '@/lib/utils'
import type { ExplorerOverviewScan } from '@/lib/api/explorer'
import { StatusIndicator } from './StatusIndicator'
import type { ExplorerStats, ExplorerType, HealthStatus } from './types'

interface SummaryBarProps {
  type: ExplorerType
  stats: ExplorerStats
  activeFilter: HealthStatus | 'all'
  onFilterChange: (filter: HealthStatus | 'all') => void
  onScan: () => void
  onFullScan: () => void
  isScanning?: boolean
  lastCompletedScan?: ExplorerOverviewScan | null
  symbolCount?: number
  staleMetadataCount?: number
  className?: string
}

const typeLabels: Record<ExplorerType, { singular: string; plural: string }> = {
  files: { singular: 'file', plural: 'files' },
  database: { singular: 'table', plural: 'tables' },
  celery: { singular: 'task', plural: 'tasks' },
  api: { singular: 'endpoint', plural: 'endpoints' },
  pages: { singular: 'page', plural: 'pages' },
  dependencies: { singular: 'dependency', plural: 'dependencies' },
  architecture: { singular: 'module', plural: 'modules' },
}


export function SummaryBar({
  type,
  stats,
  activeFilter,
  onFilterChange,
  onScan,
  onFullScan,
  isScanning = false,
  lastCompletedScan = null,
  symbolCount = 0,
  staleMetadataCount = 0,
  className,
}: SummaryBarProps) {
  const labels = typeLabels[type]

  const [timeAgo, setTimeAgo] = useState<string>('...')
  const [projectTimeAgo, setProjectTimeAgo] = useState<string>('...')
  useEffect(() => {
    const syncTimes = () => {
      setTimeAgo(formatTimeAgo(stats.lastScan, 'never'))
      setProjectTimeAgo(
        formatTimeAgo(lastCompletedScan?.completed_at || null, 'never'),
      )
    }

    syncTimes()
    const intervalId = window.setInterval(syncTimes, 60000)
    return () => window.clearInterval(intervalId)
  }, [lastCompletedScan?.completed_at, stats.lastScan])

  const metrics: {
    key: HealthStatus | 'all'
    value: number
    label: string
    status?: HealthStatus
  }[] = [
    { key: 'all', value: stats.total, label: labels.plural },
    { key: 'fresh', value: stats.fresh, label: 'fresh', status: 'fresh' },
    { key: 'stale', value: stats.stale, label: 'stale', status: 'stale' },
    { key: 'orphan', value: stats.orphan, label: 'orphaned', status: 'orphan' },
  ]

  return (
    <div
      className={cn(
        'flex items-center gap-1 px-4 py-2',
        'bg-slate-900/30 border-b border-slate-700/50',
        'text-sm',
        className,
      )}
    >
      {/* Metrics */}
      <div className="flex items-center gap-4 flex-1">
        {metrics.map((metric, idx) => (
          <button
            key={metric.key}
            onClick={() => onFilterChange(metric.key)}
            aria-pressed={activeFilter === metric.key}
            title={`Show ${metric.label}`}
            className={cn(
              'flex items-center gap-1.5 px-2 py-1 rounded-md transition-all duration-150',
              'hover:bg-slate-800/50',
              activeFilter === metric.key &&
                'bg-slate-800 ring-1 ring-slate-600',
            )}
          >
            {metric.status && (
              <StatusIndicator status={metric.status} size="sm" />
            )}
            <span
              className={cn(
                'font-mono font-semibold tabular-nums',
                metric.status === 'fresh' && 'text-phosphor-400',
                metric.status === 'stale' && 'text-amber-400',
                metric.status === 'orphan' && 'text-rose-400',
                !metric.status && 'text-slate-200',
              )}
            >
              {metric.value.toLocaleString()}
            </span>
            <span className="text-slate-500">{metric.label}</span>
            {idx < metrics.length - 1 && (
              <span className="text-slate-700 ml-2 hidden sm:inline">·</span>
            )}
          </button>
        ))}
      </div>

      {/* Scan trust signals */}
      <div className="hidden xl:flex items-center gap-2 text-xs text-slate-500">
        <Clock className="w-3 h-3" />
        <span title={formatDate(stats.lastScan)}>This view scanned {timeAgo}</span>
        <span className="text-slate-700">|</span>
        <span title={formatDate(lastCompletedScan?.completed_at || null)}>
          Project scan {projectTimeAgo}
        </span>
        <span className="text-slate-700">|</span>
        <span>{symbolCount.toLocaleString()} symbols</span>
        {staleMetadataCount > 0 && (
          <>
            <span className="text-slate-700">|</span>
            <span className="text-amber-400">
              {staleMetadataCount} stale file records
            </span>
          </>
        )}
      </div>
      <div className="hidden md:flex xl:hidden items-center gap-2 text-xs text-slate-500">
        <Clock className="w-3 h-3" />
        <span title={formatDate(stats.lastScan)}>{timeAgo}</span>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={onScan}
          disabled={isScanning}
          className={cn(
            'flex items-center gap-2 px-3 py-1.5 rounded-md',
            'text-xs font-medium transition-all duration-200',
            'border border-slate-600 hover:border-phosphor-500/50',
            'hover:bg-phosphor-500/10 hover:text-phosphor-400',
            isScanning && 'opacity-60 cursor-not-allowed',
          )}
        >
          {isScanning ? (
            <>
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Scanning...</span>
            </>
          ) : (
            <>
              <RefreshCw className="w-3.5 h-3.5" />
              <span>Scan View</span>
            </>
          )}
        </button>
        <button
          onClick={onFullScan}
          disabled={isScanning}
          title="Run a full explorer scan"
          className={cn(
            'px-3 py-1.5 rounded-md border border-slate-700',
            'text-xs font-medium text-slate-300 transition-colors',
            'hover:bg-slate-800 hover:text-slate-100',
            isScanning && 'opacity-60 cursor-not-allowed',
          )}
        >
          Full Scan
        </button>
      </div>
    </div>
  )
}

interface ScanningOverlayProps {
  className?: string
  progress?: {
    current_type: string | null
    types_completed: number
    types_total: number
    progress_pct: number
  } | null
}

/**
 * ScanningOverlay - Shows during active scan with progress
 */
export function ScanningOverlay({ className, progress }: ScanningOverlayProps) {
  return (
    <div className={cn('absolute inset-x-0 top-0 z-10', className)}>
      {/* Progress bar */}
      <div className="h-1 bg-slate-800/50 overflow-hidden">
        {progress && progress.progress_pct > 0 ? (
          <div
            className="h-full bg-phosphor-500/80 transition-all duration-300"
            style={{ width: `${progress.progress_pct}%` }}
          />
        ) : (
          <div
            className={cn(
              'h-full w-1/3',
              'bg-gradient-to-r from-transparent via-phosphor-500/60 to-transparent',
              'animate-[scan-sweep_1.5s_ease-in-out_infinite]',
            )}
          />
        )}
      </div>

      {/* Progress text */}
      {progress?.current_type && (
        <div className="absolute top-2 left-4 text-xs text-slate-400 bg-slate-900/90 px-2 py-1 rounded">
          Scanning {progress.current_type}... ({progress.types_completed}/
          {progress.types_total})
        </div>
      )}
    </div>
  )
}
