/**
 * ArchitectureRow - Row content renderer for architecture entries
 *
 * Displays module name, scan scope, violation counts by type,
 * files analyzed, and health status.
 */

import { AlertTriangle, Code2, Copy, FileCode, Layers } from 'lucide-react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { cn } from '@/lib/utils'
import { ColumnValue } from '../../DataList'
import { HealthBadge, type HealthStatus } from '../../HealthBadge'

interface ArchitectureRowProps {
  entry: ExplorerEntry
}

// Scope badge colors
const scopeBadgeStyles = {
  backend: 'bg-sky-500/20 text-sky-400 border-sky-500/30',
  frontend: 'bg-emerald-500/20 text-emerald-400 border-emerald-500/30',
  both: 'bg-purple-500/20 text-purple-400 border-purple-500/30',
} as const

// Get total violations and severity
function getViolationSummary(counts: {
  parallel_implementation?: number
  missing_infrastructure?: number
  duplicate_utility?: number
}) {
  const parallel = counts?.parallel_implementation ?? 0
  const missing = counts?.missing_infrastructure ?? 0
  const duplicate = counts?.duplicate_utility ?? 0
  const total = parallel + missing + duplicate

  // Parallel implementations are errors
  if (parallel > 0) {
    return { total, hasError: true, label: `${total}` }
  }
  // Others are warnings
  if (total > 0) {
    return { total, hasError: false, label: `${total}` }
  }
  return { total: 0, hasError: false, label: '-' }
}

export function ArchitectureRow({ entry }: ArchitectureRowProps) {
  const meta = entry.metadata
  const scanScope = (meta.scan_scope as 'backend' | 'frontend' | 'both') || 'both'
  const violationCounts = meta.violation_counts as {
    parallel_implementation?: number
    missing_infrastructure?: number
    duplicate_utility?: number
  } | undefined
  const filesAnalyzed = (meta.files_analyzed as number) ?? 0
  const healthStatus = (entry.healthStatus ?? 'unknown') as HealthStatus

  const summary = getViolationSummary(violationCounts || {})

  return (
    <>
      {/* Module icon */}
      <span className="flex-shrink-0 text-slate-500">
        <Layers className="w-4 h-4 text-rose-400/70" />
      </span>

      {/* Health indicator */}
      <HealthBadge status={healthStatus} type="architecture" size="sm" />

      {/* Module name */}
      <div className="flex-1 flex items-center gap-2 min-w-0">
        <ColumnValue className="truncate font-medium text-slate-200">
          {entry.name}
        </ColumnValue>
      </div>

      {/* Scope badge */}
      <ColumnValue width="80px" align="center">
        <span
          className={cn(
            'inline-flex px-2 py-0.5 text-[10px] font-semibold uppercase rounded border',
            scopeBadgeStyles[scanScope],
          )}
        >
          {scanScope === 'both' ? 'ALL' : scanScope === 'backend' ? 'BE' : 'FE'}
        </span>
      </ColumnValue>

      {/* Violation counts */}
      <ColumnValue width="120px" align="center">
        {summary.total > 0 ? (
          <div className="flex items-center justify-center gap-2">
            {(violationCounts?.parallel_implementation ?? 0) > 0 && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-500/15 text-red-400 border border-red-500/25"
                title="Parallel implementations"
              >
                <Code2 className="w-3 h-3" />
                <span>{violationCounts?.parallel_implementation}</span>
              </span>
            )}
            {(violationCounts?.duplicate_utility ?? 0) > 0 && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/25"
                title="Duplicate utilities"
              >
                <Copy className="w-3 h-3" />
                <span>{violationCounts?.duplicate_utility}</span>
              </span>
            )}
            {(violationCounts?.missing_infrastructure ?? 0) > 0 && (
              <span
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/15 text-amber-400 border border-amber-500/25"
                title="Missing infrastructure"
              >
                <AlertTriangle className="w-3 h-3" />
                <span>{violationCounts?.missing_infrastructure}</span>
              </span>
            )}
          </div>
        ) : (
          <span className="text-slate-600 text-xs">-</span>
        )}
      </ColumnValue>

      {/* Files analyzed */}
      <ColumnValue width="60px" align="center">
        {filesAnalyzed > 0 ? (
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-500/15 text-slate-400 border border-slate-500/25">
            <FileCode className="w-3 h-3" />
            <span>{filesAnalyzed}</span>
          </span>
        ) : (
          <span className="text-slate-600 text-[10px]">-</span>
        )}
      </ColumnValue>

      {/* Health status text */}
      <ColumnValue width="80px" align="right">
        {healthStatus === 'error' ? (
          <span className="text-red-400 text-xs">Error</span>
        ) : healthStatus === 'warning' ? (
          <span className="text-amber-400 text-xs">Warning</span>
        ) : healthStatus === 'healthy' ? (
          <span className="text-emerald-400/70 text-xs">Clean</span>
        ) : (
          <span className="text-slate-500 text-xs">Unknown</span>
        )}
      </ColumnValue>
    </>
  )
}
