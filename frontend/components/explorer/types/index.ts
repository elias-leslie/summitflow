/**
 * Explorer Type Registry
 *
 * Central configuration for all explorer types.
 * Each type provides columns, row renderer, and detail renderer.
 */

import { Database, FileText, Folder, Globe, Package, Zap } from 'lucide-react'
import type { ExplorerEntry, ExplorerEntryType } from '@/lib/api/explorer'
import type { ExplorerColumn, ExplorerType as UIExplorerType } from '../types'

export * from './database'
export * from './dependencies'
export * from './endpoints'
// Re-export type-specific components
export * from './files'
export * from './pages'
export * from './tasks'

import { TableDetail, TableRow, tableColumns } from './database'
import { DependencyDetail, DependencyRow, dependencyColumns } from './dependencies'
import { EndpointDetail, EndpointRow, endpointColumns } from './endpoints'
// Import columns
// Import row/detail components
import { FileDetail, FileRow, fileColumns } from './files'
import { PageDetail, PageRow, pageColumns } from './pages'
import { TaskDetail, TaskRow, taskColumns } from './tasks'

/**
 * Type configuration with all rendering info
 */
export interface ExplorerTypeConfig {
  /** API entry type */
  entryType: ExplorerEntryType
  /** UI display type */
  uiType: UIExplorerType
  /** Display label */
  label: string
  /** Icon component */
  icon: typeof Folder
  /** Brand color class */
  colorClass: string
  /** Column definitions */
  columns: ExplorerColumn<ExplorerEntry>[]
  /** Row content renderer */
  RowComponent: React.ComponentType<{ entry: ExplorerEntry }>
  /** Detail panel renderer */
  DetailComponent: React.ComponentType<{ entry: ExplorerEntry }>
}

/**
 * Type configurations registry
 */
export const typeConfigs: Record<ExplorerEntryType, ExplorerTypeConfig> = {
  file: {
    entryType: 'file',
    uiType: 'files',
    label: 'Files',
    icon: Folder,
    colorClass: 'text-amber-500',
    columns: fileColumns,
    RowComponent: FileRow,
    DetailComponent: FileDetail,
  },
  table: {
    entryType: 'table',
    uiType: 'database',
    label: 'Database',
    icon: Database,
    colorClass: 'text-emerald-500',
    columns: tableColumns,
    RowComponent: TableRow,
    DetailComponent: TableDetail,
  },
  task: {
    entryType: 'task',
    uiType: 'celery',
    label: 'Tasks',
    icon: Zap,
    colorClass: 'text-yellow-500',
    columns: taskColumns,
    RowComponent: TaskRow,
    DetailComponent: TaskDetail,
  },
  endpoint: {
    entryType: 'endpoint',
    uiType: 'api',
    label: 'Endpoints',
    icon: Globe,
    colorClass: 'text-cyan-500',
    columns: endpointColumns,
    RowComponent: EndpointRow,
    DetailComponent: EndpointDetail,
  },
  page: {
    entryType: 'page',
    uiType: 'pages',
    label: 'Pages',
    icon: FileText,
    colorClass: 'text-purple-500',
    columns: pageColumns,
    RowComponent: PageRow,
    DetailComponent: PageDetail,
  },
  dependency: {
    entryType: 'dependency',
    uiType: 'dependencies',
    label: 'Dependencies',
    icon: Package,
    colorClass: 'text-indigo-500',
    columns: dependencyColumns,
    RowComponent: DependencyRow,
    DetailComponent: DependencyDetail,
  },
}

/**
 * Map UI type to API entry type
 */
export const uiTypeToEntryType: Record<UIExplorerType, ExplorerEntryType> = {
  files: 'file',
  database: 'table',
  celery: 'task',
  api: 'endpoint',
  pages: 'page',
  dependencies: 'dependency',
}

/**
 * Map API entry type to UI type
 */
export const entryTypeToUiType: Record<ExplorerEntryType, UIExplorerType> = {
  file: 'files',
  table: 'database',
  task: 'celery',
  endpoint: 'api',
  page: 'pages',
  dependency: 'dependencies',
}

/**
 * Get config by UI type
 */
export function getTypeConfig(uiType: UIExplorerType): ExplorerTypeConfig {
  const entryType = uiTypeToEntryType[uiType]
  return typeConfigs[entryType]
}

/**
 * Get config by API entry type
 */
export function getTypeConfigByEntry(
  entryType: ExplorerEntryType,
): ExplorerTypeConfig {
  return typeConfigs[entryType]
}
