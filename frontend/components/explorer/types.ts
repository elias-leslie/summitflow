/**
 * Explorer Component Types
 *
 * Shared types for the unified explorer UI that handles
 * Files, Database, Celery Tasks, API Endpoints, and Pages.
 */

export type ExplorerType =
  | 'files'
  | 'database'
  | 'celery'
  | 'api'
  | 'pages'
  | 'dependencies'
  | 'architecture'

export type HealthStatus = 'fresh' | 'active' | 'stale' | 'orphan' | 'unknown'

export interface ExplorerStats {
  total: number
  fresh: number
  stale: number
  orphan: number
  lastScan: string | null
}

export interface ExplorerItem {
  id: string
  name: string
  healthStatus: HealthStatus
  // Type-specific fields handled by renderers
  [key: string]: unknown
}

export interface ExplorerTypeConfig {
  type: ExplorerType
  label: string
  icon: React.ReactNode
  color: string
  colorClass: string
  bgClass: string
  borderClass: string
}

// Column definition for data list
export interface ExplorerColumn<T = ExplorerItem> {
  key: string
  label: string
  width?: string
  align?: 'left' | 'center' | 'right'
  render?: (item: T) => React.ReactNode
}

// Filter state
export interface ExplorerFilters {
  search: string
  healthStatus: HealthStatus | 'all'
  sortField: string
  sortDir: 'asc' | 'desc'
}
