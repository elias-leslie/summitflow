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

import { useMemo } from 'react'
import { cn } from '@/lib/utils'
import { typeIcons, typeTitles } from './explorerConstants'
import { ExplorerPlaceholder } from './ExplorerPlaceholder'
import { useExplorerScan } from './hooks/useExplorerScan'
import { useExplorerShellState } from './hooks/useExplorerShellState'
import { useExplorerStats } from './hooks/useExplorerStats'
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

  const { statsData } = useExplorerStats(projectId)

  const { isScanning, scanProgress, handleScan } = useExplorerScan(
    projectId,
    activeType,
  )

  // Current stats and counts
  const stats = statsData[activeType]
  const counts = useMemo(
    () => ({
      files: statsData.files.total,
      database: statsData.database.total,
      celery: statsData.celery.total,
      api: statsData.api.total,
      pages: statsData.pages.total,
      dependencies: statsData.dependencies.total,
      architecture: statsData.architecture.total,
    }),
    [statsData],
  )

  // Props for child render function
  const childProps: ExplorerChildProps = {
    type: activeType,
    filter: activeFilter,
    sortField,
    sortDir,
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

        {/* Summary bar */}
        <SummaryBar
          type={activeType}
          stats={stats}
          activeFilter={activeFilter}
          onFilterChange={handleFilterChange}
          onScan={handleScan}
          isScanning={isScanning}
        />

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
