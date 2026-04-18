/**
 * ExplorerShell - Main layout container for unified explorer
 *
 * Three-panel layout:
 * - Left: TypeNavigator (type selector + filters)
 * - Center: Main content area (SummaryBar + DataList)
 * - Right: Optional detail sidebar (future)
 *
 * This component orchestrates the explorer state and renders
 * type-specific content based on the active type.
 */

'use client'

import { useEffect, useMemo } from 'react'
import { cn } from '@/lib/utils'
import { CodeHealthPanel } from './CodeHealthPanel'
import { ExplorerPlaceholder } from './ExplorerPlaceholder'
import { typeIcons, typeTitles, uiTypeToApiType } from './explorerConstants'
import { useExplorerOverview } from './hooks/useExplorerOverview'
import { useExplorerScan } from './hooks/useExplorerScan'
import { useExplorerShellState } from './hooks/useExplorerShellState'
import { ScanningOverlay, SummaryBar } from './SummaryBar'
import { TypeNavigator } from './TypeNavigator'
import type { ExplorerType, HealthStatus } from './types'

interface ExplorerShellProps {
  projectId: string
  initialType?: ExplorerType
  className?: string
  children?: (props: ExplorerChildProps) => React.ReactNode
  onTypeChange?: (type: ExplorerType) => void
}

export interface ExplorerChildProps {
  type: ExplorerType
  filter: HealthStatus | 'all'
  sortField: string
  sortDir: 'asc' | 'desc'
  typeLastScannedAt: string | null
  expandedIds: Set<string>
  onSort: (field: string) => void
  onToggleExpand: (id: string) => void
  onCollapseAll: () => void
}

export function ExplorerShell({
  projectId,
  initialType = 'files',
  className,
  children,
  onTypeChange: onTypeChangeProp,
}: ExplorerShellProps) {
  // Custom hooks for state management
  const {
    activeType,
    activeFilter,
    sortField,
    sortDir,
    expandedIds,
    handleTypeChange,
    handleFilterChange,
    handleSort,
    handleToggleExpand,
    handleCollapseAll,
  } = useExplorerShellState(initialType, onTypeChangeProp)

  const {
    overview,
    error: overviewError,
    refetch: refetchOverview,
  } = useExplorerOverview(projectId)

  const {
    isScanning,
    scanProgress,
    scanError,
    scanCompletedAt,
    handleScan,
    handleFullScan,
  } = useExplorerScan(projectId, activeType)

  useEffect(() => {
    if (scanCompletedAt) {
      void refetchOverview()
    }
  }, [refetchOverview, scanCompletedAt])

  // Current stats and counts
  const counts = useMemo(() => {
    const typeSummaries = overview?.type_summaries || {}
    return {
      files: typeSummaries.file?.total || 0,
      database: typeSummaries.table?.total || 0,
      tasks: typeSummaries.task?.total || 0,
      api: typeSummaries.endpoint?.total || 0,
      pages: typeSummaries.page?.total || 0,
      dependencies: typeSummaries.dependency?.total || 0,
      architecture: typeSummaries.architecture?.total || 0,
    }
  }, [overview])
  const activeSummary = overview?.type_summaries?.[uiTypeToApiType[activeType]]
  const stats = {
    total: activeSummary?.total || 0,
    fresh: activeSummary?.by_health?.healthy || 0,
    stale: activeSummary?.by_health?.warning || 0,
    orphan: activeSummary?.by_health?.error || 0,
    lastScan: activeSummary?.last_scanned || null,
  }

  // Props for child render function
  const childProps: ExplorerChildProps = {
    type: activeType,
    filter: activeFilter,
    sortField,
    sortDir,
    typeLastScannedAt: activeSummary?.last_scanned || null,
    expandedIds,
    onSort: handleSort,
    onToggleExpand: handleToggleExpand,
    onCollapseAll: handleCollapseAll,
  }

  return (
    <div
      className={cn(
        'flex h-full overflow-hidden rounded-lg',
        'bg-slate-850 border border-slate-700/50',
        className,
      )}
    >
      {/* Left: Type Navigator */}
      <TypeNavigator
        activeType={activeType}
        onTypeChange={handleTypeChange}
        activeFilter={activeFilter}
        onFilterChange={handleFilterChange}
        counts={counts}
      />

      {/* Center: Main content */}
      <div className="flex-1 flex flex-col min-w-0 relative">
        {/* Scanning overlay */}
        {isScanning && <ScanningOverlay progress={scanProgress} />}

        {/* Header */}
        <div
          className={cn(
            'flex items-center gap-3 px-4 py-3',
            'border-b border-slate-700/50',
          )}
        >
          <span className="text-slate-400">{typeIcons[activeType]}</span>
          <h2 className="text-lg font-semibold text-slate-100 display">
            {typeTitles[activeType]}
          </h2>
        </div>

        {(overviewError || scanError) && (
          <div className="border-b border-rose-900/40 bg-rose-950/20 px-4 py-2 text-xs text-rose-300">
            {scanError || overviewError}
          </div>
        )}

        {/* Summary bar */}
        <SummaryBar
          type={activeType}
          stats={stats}
          activeFilter={activeFilter}
          onFilterChange={handleFilterChange}
          onScan={handleScan}
          onFullScan={handleFullScan}
          isScanning={isScanning}
          lastCompletedScan={overview?.last_completed_scan || null}
          symbolCount={overview?.symbol_stats?.count || 0}
          staleMetadataCount={overview?.stale_metadata_count || 0}
        />

        {/* Code Health Panel - only shown for files view */}
        {activeType === 'files' && <CodeHealthPanel projectId={projectId} />}

        {/* Content area */}
        <div className="flex-1 overflow-hidden">
          {children ? (
            children(childProps)
          ) : (
            <ExplorerPlaceholder type={activeType} />
          )}
        </div>
      </div>
    </div>
  )
}

/**
 * ExplorerHeader - Alternative standalone header component
 */
export function ExplorerHeader({
  type,
  title,
  actions,
  className,
}: {
  type: ExplorerType
  title?: string
  actions?: React.ReactNode
  className?: string
}) {
  return (
    <div
      className={cn(
        'flex items-center justify-between gap-4 px-4 py-3',
        'border-b border-slate-700/50',
        className,
      )}
    >
      <div className="flex items-center gap-3">
        <span className="text-slate-400">{typeIcons[type]}</span>
        <h2 className="text-lg font-semibold text-slate-100 display">
          {title || typeTitles[type]}
        </h2>
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  )
}
