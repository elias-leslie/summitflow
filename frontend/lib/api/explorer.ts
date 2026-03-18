/**
 * Explorer API Client
 *
 * API client for the unified explorer endpoints.
 * Follows existing patterns from lib/api.ts.
 *
 * Related modules:
 * - explorer-analysis.ts: Coverage gaps and refactor targets
 * - explorer-scan.ts: Scan operations, history, and comparisons
 */

import { buildQueryString, fetchWithErrorHandling } from './utils'

// ============================================================================
// Types - Aligned with backend API contract (docs/explorer-architecture.md)
// ============================================================================

export type ExplorerEntryType =
  | 'file'
  | 'table'
  | 'task'
  | 'endpoint'
  | 'page'
  | 'dependency'
  | 'architecture'
export type ExplorerHealthStatus = 'healthy' | 'warning' | 'error' | 'unknown'

export interface ExplorerEntryMetadata {
  // File metadata
  is_directory?: boolean
  extension?: string
  size_bytes?: number
  lines_of_code?: number
  file_count?: number
  symbol_count?: number
  symbol_kinds?: Record<string, number> | null
  bloat_level?: 'warning' | 'critical' | null
  stale_status?: 'fresh' | 'stale' | 'orphan' | 'untracked' | null
  last_commit_days?: number
  last_commit_hash?: string
  last_commit_message?: string

  // Database metadata
  row_count?: number
  column_count?: number
  columns?: string[]
  columns_with_data?: string[]
  columns_mostly_null?: string[]
  completeness_pct?: number
  freshness_days?: number
  category?: string
  relationships?: {
    references?: string[]
    referenced_by?: string[]
  }

  // Task metadata
  task_path?: string
  function_name?: string
  schedule_type?: string
  schedule_value?: string
  schedule_human?: string
  last_run_at?: string
  success_count_7d?: number
  failure_count_7d?: number
  success_rate_pct?: number
  avg_duration_ms?: number
  reads_tables?: string[]
  writes_tables?: string[]
  depends_on_tasks?: string[]
  called_by?: string[]

  // Endpoint metadata
  method?: string
  port?: number
  source_file?: string
  http_status?: number
  response_time_ms?: number
  console_errors?: number
  console_warnings?: number
  depends_on_tables?: string[]
  called_by_frontend?: string[]
  last_health_check?: string

  // Page metadata
  route_params?: string[]
  url?: string

  // Dependency metadata
  package_type?: 'python' | 'nodejs'
  constraint?: string
  locked_version?: string
  latest_version?: string
  is_outdated?: boolean
  is_workspace_ref?: boolean
  is_dev_dependency?: boolean
  vulnerabilities?: {
    critical: number
    high: number
    medium: number
    low: number
  }
  audit_advisories?: string[]

  // Generic extension
  [key: string]: unknown
}

export interface ExplorerEntry {
  id: number
  entryType: ExplorerEntryType
  path: string
  name: string
  healthStatus: ExplorerHealthStatus
  lastScannedAt: string | null
  metadata: ExplorerEntryMetadata
  // Evidence fields (explorer-driven evidence capture)
  evidenceCount?: number
  lastEvidenceAt?: string | null
}

export interface ExplorerStats {
  byHealth: Record<ExplorerHealthStatus, number>
  byType: Record<ExplorerEntryType, number>
  lastScanned?: string | null
}

export interface ExplorerResponse {
  entries: ExplorerEntry[]
  total: number
  stats: ExplorerStats
}

export interface StatsResponse {
  byType: Record<ExplorerEntryType, number>
  byHealth: Record<ExplorerHealthStatus, number>
  total: number
  lastScanned: string | null
}

export interface ExplorerSymbol {
  id: number
  project_id: string
  file_path: string
  symbol_id: string
  qualified_name: string
  name: string
  kind: string
  signature: string
  language: string
  start_line: number
  end_line: number
  byte_offset: number
  byte_length: number
  content_hash: string
  summary: string | null
  keywords: string[]
  created_at: string
  updated_at: string
}

export interface ExplorerSymbolSearchResponse {
  query: string
  count: number
  items: ExplorerSymbol[]
}

export interface ExplorerSymbolDetailResponse {
  symbol: ExplorerSymbol
  source: string
  file_entry: ExplorerEntry | null
  related_entries: ExplorerEntry[]
}

export interface ExplorerTypeSummary {
  total: number
  by_health: Record<ExplorerHealthStatus, number>
  last_scanned: string | null
}

export interface ExplorerOverviewScan {
  id: number
  scan_type: string
  triggered_by: string
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  started_at: string
  completed_at: string | null
}

export interface ExplorerOverview {
  scan_status: {
    status: 'idle' | 'running' | 'completed' | 'failed'
    current_type: string | null
    types_total: number
    types_completed: number
    progress_pct: number
    started_at: string | null
    completed_at: string | null
    error: string | null
    results: Array<{
      entry_type: string
      entries_found: number
      entries_saved: number
      duration_ms: number
      success: boolean
    }>
  }
  latest_scan: ExplorerOverviewScan | null
  last_completed_scan: ExplorerOverviewScan | null
  history_summary: {
    total_scans: number
    avg_duration_ms: number | null
    complexity_trend: 'improving' | 'stable' | 'degrading' | 'unknown'
    most_active_trigger: string | null
    triggers_breakdown: Array<{
      trigger: string
      count: number
      percentage: number
    }>
  }
  type_summaries: Partial<Record<ExplorerEntryType, ExplorerTypeSummary>>
  symbol_stats: {
    count: number
    last_updated: string | null
  }
  stale_metadata_count: number
}

interface RawExplorerEntry {
  id: number
  entry_type: ExplorerEntryType
  path: string
  name: string
  health_status: ExplorerHealthStatus
  last_scanned_at: string | null
  metadata: ExplorerEntryMetadata
  evidence_count?: number
  last_evidence_at?: string | null
}

function normalizeExplorerEntry(entry: RawExplorerEntry | ExplorerEntry): ExplorerEntry {
  if ('entryType' in entry) {
    return entry
  }
  return {
    id: entry.id,
    entryType: entry.entry_type,
    path: entry.path,
    name: entry.name,
    healthStatus: entry.health_status,
    lastScannedAt: entry.last_scanned_at,
    metadata: entry.metadata ?? {},
    evidenceCount: entry.evidence_count,
    lastEvidenceAt: entry.last_evidence_at,
  }
}

// ============================================================================
// Filter Types
// ============================================================================

export interface ExplorerFilters {
  type?: ExplorerEntryType
  health?: ExplorerHealthStatus
  path?: string
  sort?: 'path' | 'name' | 'health_status' | 'last_scanned_at'
  dir?: 'asc' | 'desc'
  limit?: number
  offset?: number
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Fetch explorer entries with optional filters.
 */
export async function fetchExplorerEntries(
  projectId: string,
  filters: ExplorerFilters = {},
): Promise<ExplorerResponse> {
  const query = buildQueryString({
    type: filters.type,
    health: filters.health,
    path: filters.path,
    sort: filters.sort,
    dir: filters.dir,
    limit: filters.limit,
    offset: filters.offset,
  })
  return fetchWithErrorHandling<ExplorerResponse>(
    `/api/projects/${projectId}/explorer${query}`,
    { errorMessage: 'Failed to fetch explorer entries' },
  )
}

/**
 * Fetch aggregated statistics for explorer entries.
 */
export async function fetchExplorerStats(
  projectId: string,
): Promise<StatsResponse> {
  return fetchWithErrorHandling<StatsResponse>(
    `/api/projects/${projectId}/explorer/stats`,
    { errorMessage: 'Failed to fetch explorer stats' },
  )
}

export async function fetchExplorerOverview(
  projectId: string,
): Promise<ExplorerOverview> {
  return fetchWithErrorHandling<ExplorerOverview>(
    `/api/projects/${projectId}/explorer/overview`,
    { errorMessage: 'Failed to fetch explorer overview' },
  )
}

/**
 * Fetch direct children of a path for tree navigation.
 */
export async function fetchExplorerChildren(
  projectId: string,
  type: ExplorerEntryType,
  parentPath: string = '',
): Promise<ExplorerEntry[]> {
  const query = buildQueryString({ type, path: parentPath })
  return fetchWithErrorHandling<ExplorerEntry[]>(
    `/api/projects/${projectId}/explorer/children${query}`,
    { errorMessage: 'Failed to fetch explorer children' },
  )
}

export async function searchExplorerSymbols(
  projectId: string,
  params: {
    q: string
    language?: string
    kind?: string
    limit?: number
  },
): Promise<ExplorerSymbolSearchResponse> {
  const query = buildQueryString({
    q: params.q,
    language: params.language,
    kind: params.kind,
    limit: params.limit,
  })
  return fetchWithErrorHandling<ExplorerSymbolSearchResponse>(
    `/api/projects/${projectId}/explorer/symbols/search${query}`,
    { errorMessage: 'Failed to search explorer symbols' },
  )
}

export async function fetchExplorerSymbolDetail(
  projectId: string,
  params: {
    symbolId: string
    contextLines?: number
  },
): Promise<ExplorerSymbolDetailResponse> {
  const query = buildQueryString({
    symbol_id: params.symbolId,
    context_lines: params.contextLines,
  })
  const response = await fetchWithErrorHandling<ExplorerSymbolDetailResponse & {
    file_entry: RawExplorerEntry | ExplorerEntry | null
    related_entries: Array<RawExplorerEntry | ExplorerEntry>
  }>(
    `/api/projects/${projectId}/explorer/symbols/detail${query}`,
    { errorMessage: 'Failed to fetch symbol detail' },
  )
  return {
    ...response,
    file_entry: response.file_entry ? normalizeExplorerEntry(response.file_entry) : null,
    related_entries: response.related_entries.map(normalizeExplorerEntry),
  }
}
