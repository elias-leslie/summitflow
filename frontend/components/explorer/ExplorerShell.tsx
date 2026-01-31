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

import { useQueryClient } from '@tanstack/react-query'
import {
  Database,
  FileText,
  Folder,
  Globe,
  Layers,
  Package,
  Zap,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  type ExplorerEntryType,
  fetchExplorerEntries,
  fetchScanStatus,
  type ScanStatusResponse,
  triggerExplorerScan,
} from '@/lib/api/explorer'
import { scanHistoryKeys } from '@/lib/hooks/useScanHistory'
import { cn } from '@/lib/utils'
import { CodeHealthPanel } from './CodeHealthPanel'
import { explorerKeys } from './hooks/useExplorerData'
import { ScanningOverlay, SummaryBar } from './SummaryBar'
import { TypeNavigator } from './TypeNavigator'
import type { ExplorerStats, ExplorerType, HealthStatus } from './types'

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

// Map UI type to API entry type
const uiTypeToApiType: Record<ExplorerType, ExplorerEntryType> = {
  files: 'file',
  database: 'table',
  celery: 'task',
  api: 'endpoint',
  pages: 'page',
  dependencies: 'dependency',
  architecture: 'architecture',
}

const typeIcons: Record<ExplorerType, React.ReactNode> = {
  files: <Folder className="w-5 h-5" />,
  database: <Database className="w-5 h-5" />,
  celery: <Zap className="w-5 h-5" />,
  api: <Globe className="w-5 h-5" />,
  pages: <FileText className="w-5 h-5" />,
  dependencies: <Package className="w-5 h-5" />,
  architecture: <Layers className="w-5 h-5" />,
}

const typeTitles: Record<ExplorerType, string> = {
  files: 'Files Explorer',
  database: 'Database Tables',
  celery: 'Celery Tasks',
  api: 'API Endpoints',
  pages: 'Frontend Pages',
  dependencies: 'Dependencies',
  architecture: 'Architecture',
}

export function ExplorerShell({
  projectId,
  initialType = 'files',
  className,
  children,
  onTypeChange: onTypeChangeProp,
}: ExplorerShellProps) {
  const queryClient = useQueryClient()

  // Explorer state
  const [activeType, setActiveType] = useState<ExplorerType>(initialType)
  const [activeFilter, setActiveFilter] = useState<HealthStatus | 'all'>('all')
  const [sortField, setSortField] = useState('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())
  const [isScanning, setIsScanning] = useState(false)
  const [scanProgress, setScanProgress] = useState<ScanStatusResponse | null>(
    null,
  )

  // Stats state - fetched from API
  const [statsData, setStatsData] = useState<
    Record<ExplorerType, ExplorerStats>
  >({
    files: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    database: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    celery: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    api: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    pages: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    dependencies: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
    architecture: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
  })

  // Fetch stats for all types on mount and when scanning completes
  useEffect(() => {
    const fetchAllStats = async () => {
      const types: ExplorerType[] = [
        'files',
        'database',
        'celery',
        'api',
        'pages',
        'dependencies',
        'architecture',
      ]
      // Start with empty stats object to avoid dependency on statsData
      const newStats: Record<ExplorerType, ExplorerStats> = {
        files: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
        database: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
        celery: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
        api: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
        pages: { total: 0, fresh: 0, stale: 0, orphan: 0, lastScan: null },
        dependencies: {
          total: 0,
          fresh: 0,
          stale: 0,
          orphan: 0,
          lastScan: null,
        },
        architecture: {
          total: 0,
          fresh: 0,
          stale: 0,
          orphan: 0,
          lastScan: null,
        },
      }

      for (const type of types) {
        try {
          const apiType = uiTypeToApiType[type]
          const response = await fetchExplorerEntries(projectId, {
            type: apiType,
            limit: 1, // Just need stats, not entries
          })

          // Map API health statuses to UI stats
          const byHealth = response.stats?.byHealth || {}
          newStats[type] = {
            total: response.total || 0,
            fresh: (byHealth.healthy || 0) as number,
            stale: (byHealth.warning || 0) as number,
            orphan: (byHealth.error || 0) as number,
            lastScan: response.stats?.lastScanned || null,
          }
        } catch (err) {
          console.error(`Failed to fetch stats for ${type}:`, err)
        }
      }

      setStatsData(newStats)
    }

    fetchAllStats()
    // NOTE: statsData intentionally omitted - including it would cause infinite loop
    // We construct newStats fresh each time instead of spreading statsData
  }, [projectId]) // Re-fetch when scanning completes

  // Handlers
  const handleTypeChange = useCallback(
    (type: ExplorerType) => {
      setActiveType(type)
      setActiveFilter('all') // Reset filter on type change
      setExpandedIds(new Set()) // Reset expansion on type change
      setSortField('name')
      setSortDir('asc')
      onTypeChangeProp?.(type) // Notify parent of type change
    },
    [onTypeChangeProp],
  )

  const handleFilterChange = useCallback((filter: HealthStatus | 'all') => {
    setActiveFilter(filter)
  }, [])

  const handleSort = useCallback(
    (field: string) => {
      if (sortField === field) {
        setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
      } else {
        setSortField(field)
        setSortDir('asc')
      }
    },
    [sortField],
  )

  const handleToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev)
      if (next.has(id)) {
        next.delete(id)
      } else {
        next.add(id)
      }
      return next
    })
  }, [])

  const handleCollapseAll = useCallback(() => {
    setExpandedIds(new Set())
  }, [])

  const handleScan = useCallback(async () => {
    setIsScanning(true)
    setScanProgress(null)

    try {
      const apiType = uiTypeToApiType[activeType]
      await triggerExplorerScan(
        projectId,
        apiType as 'file' | 'table' | 'task' | 'endpoint' | 'page',
      )

      // Poll for completion every 500ms
      const pollInterval = setInterval(async () => {
        try {
          const status = await fetchScanStatus(projectId)
          setScanProgress(status)

          if (status.status === 'completed' || status.status === 'failed') {
            clearInterval(pollInterval)
            setIsScanning(false)
            setScanProgress(null)

            // Invalidate caches so UI updates immediately
            queryClient.invalidateQueries({ queryKey: scanHistoryKeys.all })
            queryClient.invalidateQueries({
              queryKey: explorerKeys.entries(projectId),
            })
            queryClient.invalidateQueries({
              queryKey: explorerKeys.stats(projectId),
            })

            if (status.status === 'failed' && status.error) {
              console.error('Scan completed with error:', status.error)
            }
          }
        } catch (pollErr) {
          console.error('Poll failed:', pollErr)
          clearInterval(pollInterval)
          setIsScanning(false)
          setScanProgress(null)
        }
      }, 500)

      // Safety timeout after 60 seconds
      setTimeout(() => {
        clearInterval(pollInterval)
        if (isScanning) {
          setIsScanning(false)
          setScanProgress(null)
        }
      }, 60000)
    } catch (err) {
      console.error('Scan failed:', err)
      setIsScanning(false)
      setScanProgress(null)
    }
  }, [projectId, activeType, isScanning, queryClient])

  // Current stats
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
 * Placeholder content when no children provided
 */
function ExplorerPlaceholder({ type }: { type: ExplorerType }) {
  return (
    <div className="flex flex-col items-center justify-center h-full text-slate-500">
      <div className="opacity-20 mb-4">{typeIcons[type]}</div>
      <p className="text-sm">{typeTitles[type]} content will render here</p>
      <p className="text-xs text-slate-600 mt-1">
        Connect data source to display items
      </p>
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
