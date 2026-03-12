/**
 * CodeHealthPanel - Diagnostic terminal aesthetic for code health monitoring
 *
 * Orchestrates code health visualization components:
 * - HealthMetricsBar with triage counts
 * - FilterBar for priority filtering
 * - Sortable RefactorTargetsTable with expandable rows
 */

'use client'

import {
  Activity,
  AlertCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Loader2,
} from 'lucide-react'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import { FilterBar } from './FilterBar'
import { HealthMetricsBar } from './HealthMetricsBar'
import { useRefactorTargets } from './hooks/useRefactorTargets'
import { RefactorTargetsTable } from './RefactorTargetsTable'
import { ScanTrendLine } from './ScanTrendLine'

interface CodeHealthPanelProps {
  projectId: string
  onFileSelect?: (path: string) => void
  className?: string
}

export function CodeHealthPanel({
  projectId,
  onFileSelect,
  className,
}: CodeHealthPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true)

  const {
    data,
    isLoading,
    error,
    filteredTargets,
    highCount,
    mediumCount,
    totalComplexity,
    totalTargets,
    actionableCount,
    observeOnlyCount,
    priorityFilter,
    setPriorityFilter,
    sortField,
    sortDir,
    toggleSort,
    expandedRows,
    toggleRow,
  } = useRefactorTargets(projectId)

  if (error) {
    return (
      <div
        className={cn('border border-red-500/30 bg-red-950/20 p-4', className)}
      >
        <div className="flex items-center gap-2 text-red-400 text-sm">
          <AlertCircle className="w-4 h-4" />
          <span>Failed to load code health data</span>
        </div>
      </div>
    )
  }

  return (
    <div
      className={cn(
        'border border-slate-700/50 bg-gradient-to-b from-slate-900/80 to-slate-950/90',
        'font-mono text-sm',
        className,
      )}
    >
      {/* Header - Diagnostic Terminal Style */}
      <button
        type="button"
        onClick={() => setIsExpanded(!isExpanded)}
        className="w-full flex items-center justify-between px-4 py-3 hover:bg-slate-800/30 transition-colors border-b border-slate-700/30"
      >
        <div className="flex items-center gap-3">
          {isExpanded ? (
            <ChevronDown className="w-4 h-4 text-emerald-500" />
          ) : (
            <ChevronRight className="w-4 h-4 text-slate-500" />
          )}
          <Activity className="w-4 h-4 text-emerald-500" />
          <span className="text-emerald-400 font-semibold tracking-wide">
            CODE HEALTH DIAGNOSTIC
          </span>
          {isLoading && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-500 ml-2" />
          )}
        </div>

        {/* Triage counts in header */}
        <div className="flex items-center gap-4 text-xs">
          {actionableCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-emerald-950/50 border border-emerald-500/30">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-emerald-400 font-medium">
                {actionableCount} ACTIONABLE
              </span>
            </div>
          )}
          {observeOnlyCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-slate-900/70 border border-slate-700/50">
              <div className="w-2 h-2 rounded-full bg-slate-500" />
              <span className="text-slate-300 font-medium">
                {observeOnlyCount} WATCHLIST
              </span>
            </div>
          )}
          {highCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-red-950/50 border border-red-500/30">
              <div className="w-2 h-2 rounded-full bg-red-500 animate-pulse" />
              <span className="text-red-400 font-medium">
                {highCount} CRITICAL
              </span>
            </div>
          )}
          {mediumCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-amber-950/50 border border-amber-500/30">
              <div className="w-2 h-2 rounded-full bg-amber-500" />
              <span className="text-amber-400 font-medium">
                {mediumCount} WARNING
              </span>
            </div>
          )}
          {totalTargets === 0 && !isLoading && (
            <div className="flex items-center gap-1.5 px-2 py-1 rounded bg-emerald-950/50 border border-emerald-500/30">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-emerald-400 font-medium">ALL CLEAR</span>
            </div>
          )}
        </div>
      </button>

      {isExpanded && (
        <div className="p-4 space-y-4">
          {/* Stale data warning */}
          {data?.warning && (
            <div className="flex items-center gap-2 px-3 py-2 rounded bg-amber-950/30 border border-amber-500/30 text-xs">
              <AlertTriangle className="w-4 h-4 text-amber-500 flex-shrink-0" />
              <span className="text-amber-300">{data.warning.message}</span>
            </div>
          )}

          {/* Metrics Bar */}
          <HealthMetricsBar
            highCount={highCount}
            mediumCount={mediumCount}
            totalComplexity={totalComplexity}
            isLoading={isLoading}
          />

          {/* Scan History Trend */}
          <ScanTrendLine projectId={projectId} />

          {/* Filter Bar */}
          <FilterBar
            activeFilter={priorityFilter}
            onFilterChange={setPriorityFilter}
            highCount={highCount}
            mediumCount={mediumCount}
          />

          {/* Targets Table */}
          <RefactorTargetsTable
            targets={filteredTargets}
            sortField={sortField}
            sortDir={sortDir}
            onSort={toggleSort}
            expandedRows={expandedRows}
            onToggleRow={toggleRow}
            onFileSelect={onFileSelect}
            isLoading={isLoading}
          />
        </div>
      )}
    </div>
  )
}
