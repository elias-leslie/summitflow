/**
 * ExplorerTab - Integrated explorer component for project page
 *
 * Wires together:
 * - ExplorerShell (layout)
 * - Hooks (data, state, filters)
 * - Type renderers (row, detail, columns)
 */

'use client'

import { useCallback } from 'react'
import type { ExplorerEntry } from '@/lib/api/explorer'
import { DataList } from './DataList'
import { DataRow } from './DataRow'
import { ExplorerShell } from './ExplorerShell'
import {
  useDedupedDependencies,
  useExplorerData,
  useExplorerFilters,
  useExplorerState,
} from './hooks'
import { SymbolSearchPanel } from './SymbolSearchPanel'
import type { ExplorerType, HealthStatus } from './types'
import { getTypeConfig, uiTypeToEntryType } from './types/index'

interface ExplorerTabProps {
  projectId: string
  initialType?: ExplorerType
  onTypeChange?: (type: ExplorerType) => void
}

export function ExplorerTab({
  projectId,
  initialType = 'files',
  onTypeChange,
}: ExplorerTabProps) {
  return (
    <ExplorerShell
      projectId={projectId}
      initialType={initialType}
      onTypeChange={onTypeChange}
      className="h-[calc(100vh-280px)] min-h-[500px]"
    >
      {(props) => (
        <ExplorerContent
          projectId={projectId}
          type={props.type}
          filter={props.filter}
          sortField={props.sortField}
          sortDir={props.sortDir}
          typeLastScannedAt={props.typeLastScannedAt}
          onSort={props.onSort}
        />
      )}
    </ExplorerShell>
  )
}

interface ExplorerContentProps {
  projectId: string
  type: ExplorerType
  filter: HealthStatus | 'all'
  sortField: string
  sortDir: 'asc' | 'desc'
  typeLastScannedAt: string | null
  onSort: (field: string) => void
}

function ExplorerContent({
  projectId,
  type,
  filter,
  sortField,
  sortDir,
  typeLastScannedAt,
  onSort,
}: ExplorerContentProps) {
  // Convert UI type to API entry type
  const entryType = uiTypeToEntryType[type]
  const typeConfig = getTypeConfig(type)

  // Get filter configuration
  const { filters } = useExplorerFilters({
    initialType: entryType,
    initialHealth: filter === 'all' ? 'all' : mapHealthStatus(filter),
    initialSort: sortField as
      | 'path'
      | 'name'
      | 'health_status'
      | 'last_scanned_at',
    initialSortDir: sortDir,
  })

  // Fetch data
  const {
    entries: rawEntries,
    isLoading,
    isError,
  } = useExplorerData({
    projectId,
    filters: {
      ...filters,
      type: entryType,
      health: filter === 'all' ? undefined : mapHealthStatus(filter),
      sort: sortField as 'path' | 'name' | 'health_status' | 'last_scanned_at',
      dir: sortDir,
    },
  })

  // Deduplicate dependencies by package name
  const dedupedDependencies = useDedupedDependencies(
    type === 'dependencies' ? rawEntries : [],
  )
  // Use deduplicated entries for dependencies, raw entries for other types
  const entries = type === 'dependencies' ? dedupedDependencies : rawEntries

  // UI state
  const { isExpanded, toggleExpand } = useExplorerState()

  // Get type-specific components
  const { RowComponent, DetailComponent, columns } = typeConfig

  // Render a single row
  const renderRow = useCallback(
    (entry: ExplorerEntry) => (
      <DataRow
        key={entry.id}
        id={String(entry.id)}
        healthStatus={mapApiHealthToUi(entry.healthStatus)}
        isExpanded={isExpanded(String(entry.id))}
        onToggle={toggleExpand}
        renderContent={() => <RowComponent entry={entry} />}
        renderDetail={() => <DetailComponent entry={entry} />}
      />
    ),
    [RowComponent, DetailComponent, isExpanded, toggleExpand],
  )

  if (isError) {
    return (
      <div className="flex items-center justify-center h-full text-slate-500">
        <p>Failed to load explorer data</p>
      </div>
    )
  }

  return (
    <div className="flex h-full flex-col">
      {type === 'files' ? <SymbolSearchPanel projectId={projectId} /> : null}
      <div className="min-h-0 flex-1">
        <DataList
          items={entries}
          columns={columns}
          sortField={sortField}
          sortDir={sortDir}
          onSort={onSort}
          renderRow={renderRow}
          isLoading={isLoading}
          emptyMessage={
            typeLastScannedAt
              ? `No ${typeConfig.label.toLowerCase()} match the current filters`
              : `No ${typeConfig.label.toLowerCase()} indexed yet. Run a scan to populate Explorer.`
          }
        />
      </div>
    </div>
  )
}

// Map UI health status to API health status
function mapHealthStatus(
  status: HealthStatus,
): 'healthy' | 'warning' | 'error' | 'unknown' {
  // UI uses: fresh, active, stale, orphan, unknown
  // API uses: healthy, warning, error, unknown
  switch (status) {
    case 'fresh':
    case 'active':
      return 'healthy'
    case 'stale':
      return 'warning'
    case 'orphan':
      return 'error'
    default:
      return 'unknown'
  }
}

// Map API health status to UI health status
function mapApiHealthToUi(status: string): HealthStatus {
  switch (status) {
    case 'healthy':
      return 'fresh'
    case 'warning':
      return 'stale'
    case 'error':
      return 'orphan'
    default:
      return 'unknown'
  }
}
