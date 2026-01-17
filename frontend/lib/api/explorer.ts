/**
 * Explorer API Client
 *
 * API client for the unified explorer endpoints.
 * Follows existing patterns from lib/api.ts.
 */

// ============================================================================
// Types - Aligned with backend API contract (docs/explorer-architecture.md)
// ============================================================================

export type ExplorerEntryType = 'file' | 'table' | 'task' | 'endpoint' | 'page'
export type ExplorerHealthStatus = 'healthy' | 'warning' | 'error' | 'unknown'

export interface ExplorerEntryMetadata {
  // File metadata
  is_directory?: boolean
  extension?: string
  size_bytes?: number
  lines_of_code?: number
  file_count?: number
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

export interface ScanResponse {
  status: string
  message: string
  type: ExplorerEntryType | null
}

export interface ScanStatusResponse {
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
  const params = new URLSearchParams()

  if (filters.type) params.append('type', filters.type)
  if (filters.health) params.append('health', filters.health)
  if (filters.path) params.append('path', filters.path)
  if (filters.sort) params.append('sort', filters.sort)
  if (filters.dir) params.append('dir', filters.dir)
  if (filters.limit !== undefined)
    params.append('limit', filters.limit.toString())
  if (filters.offset !== undefined)
    params.append('offset', filters.offset.toString())

  const queryString = params.toString()
  const res = await fetch(
    `/api/projects/${projectId}/explorer${queryString ? `?${queryString}` : ''}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch explorer entries' }))
    throw new Error(error.detail || 'Failed to fetch explorer entries')
  }
  return res.json()
}

/**
 * Fetch aggregated statistics for explorer entries.
 */
export async function fetchExplorerStats(
  projectId: string,
): Promise<StatsResponse> {
  const res = await fetch(`/api/projects/${projectId}/explorer/stats`)
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch explorer stats' }))
    throw new Error(error.detail || 'Failed to fetch explorer stats')
  }
  return res.json()
}

/**
 * Fetch a single explorer entry by type and path.
 */
export async function fetchExplorerEntry(
  projectId: string,
  type: ExplorerEntryType,
  path: string,
): Promise<ExplorerEntry> {
  const res = await fetch(
    `/api/projects/${projectId}/explorer/${type}/${encodeURIComponent(path)}`,
  )
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(`Entry not found: ${type}/${path}`)
    }
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch explorer entry' }))
    throw new Error(error.detail || 'Failed to fetch explorer entry')
  }
  return res.json()
}

/**
 * Fetch a single explorer entry by ID.
 */
export async function fetchExplorerEntryById(
  projectId: string,
  entryId: number,
): Promise<ExplorerEntry> {
  const res = await fetch(
    `/api/projects/${projectId}/explorer/entry/${entryId}`,
  )
  if (!res.ok) {
    if (res.status === 404) {
      throw new Error(`Entry ${entryId} not found`)
    }
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch explorer entry' }))
    throw new Error(error.detail || 'Failed to fetch explorer entry')
  }
  return res.json()
}

/**
 * Fetch direct children of a path for tree navigation.
 */
export async function fetchExplorerChildren(
  projectId: string,
  type: ExplorerEntryType,
  parentPath: string = '',
): Promise<ExplorerEntry[]> {
  const params = new URLSearchParams({
    type,
    path: parentPath,
  })

  const res = await fetch(
    `/api/projects/${projectId}/explorer/children?${params}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch explorer children' }))
    throw new Error(error.detail || 'Failed to fetch explorer children')
  }
  return res.json()
}

/**
 * Trigger a scan for explorer entries.
 * Runs in background, returns immediately.
 *
 * @param projectId - Project to scan
 * @param type - Optional entry type to scan (scans all if not specified)
 */
export async function triggerExplorerScan(
  projectId: string,
  type?: ExplorerEntryType,
): Promise<ScanResponse> {
  const params = new URLSearchParams()
  if (type) params.append('type', type)

  const queryString = params.toString()
  const res = await fetch(
    `/api/projects/${projectId}/explorer/scan${queryString ? `?${queryString}` : ''}`,
    { method: 'POST' },
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to trigger scan' }))
    throw new Error(error.detail || 'Failed to trigger scan')
  }
  return res.json()
}

/**
 * Get current scan status for polling.
 *
 * @param projectId - Project to check
 */
export async function fetchScanStatus(
  projectId: string,
): Promise<ScanStatusResponse> {
  const res = await fetch(`/api/projects/${projectId}/explorer/scan/status`)
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch scan status' }))
    throw new Error(error.detail || 'Failed to fetch scan status')
  }
  return res.json()
}

// ============================================================================
// Analysis Types
// ============================================================================

export interface CoverageGapsSummary {
  total_uncovered: number
  endpoint_count: number
  page_count: number
  table_count: number
}

export interface CoverageGapsResponse {
  summary: CoverageGapsSummary
  uncovered_endpoints: Array<{ id: number; path: string; name: string }>
  uncovered_pages: Array<{ id: number; path: string; name: string }>
  uncovered_tables: Array<{ id: number; path: string; name: string }>
}

export interface RefactorTarget {
  path: string
  name: string
  complexity_score: number
  lines_of_code: number
  function_count: number
  class_count: number
  priority: 'high' | 'medium' | 'low'
  reason: string
}

export interface RefactorTargetsResponse {
  targets: RefactorTarget[]
  summary: {
    high_priority_count: number
    medium_priority_count: number
    total_complexity: number
  }
  warning?: {
    message: string
    stale_count: number
  }
}

// ============================================================================
// Analysis API Functions
// ============================================================================

/**
 * Fetch coverage gaps (uncovered endpoints, pages, tables).
 */
export async function fetchCoverageGaps(
  projectId: string,
): Promise<CoverageGapsResponse> {
  const res = await fetch(`/api/projects/${projectId}/analysis/coverage-gaps`)
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch coverage gaps' }))
    throw new Error(error.detail || 'Failed to fetch coverage gaps')
  }
  return res.json()
}

/**
 * Fetch files that are refactoring candidates.
 *
 * @param projectId - Project to fetch targets for
 * @param options - Optional filters
 * @param options.codeOnly - Filter to code files only (default: true)
 * @param options.extensions - Comma-separated list of extensions to include
 * @param options.limit - Max results (default: 50)
 */
export async function fetchRefactorTargets(
  projectId: string,
  options: {
    codeOnly?: boolean
    extensions?: string
    limit?: number
  } = {},
): Promise<RefactorTargetsResponse> {
  const params = new URLSearchParams()

  // Default to code_only=true
  params.append('code_only', String(options.codeOnly ?? true))

  if (options.extensions) {
    params.append('extensions', options.extensions)
  }
  if (options.limit !== undefined) {
    params.append('limit', String(options.limit))
  }

  const res = await fetch(
    `/api/projects/${projectId}/explorer/refactor-targets?${params}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch refactor targets' }))
    throw new Error(error.detail || 'Failed to fetch refactor targets')
  }
  return res.json()
}

// ============================================================================
// Scan History Types
// ============================================================================

export interface ScanHistoryEntry {
  id: number
  project_id: string
  scan_type: string // 'file', 'page', 'endpoint', 'database', 'task', 'full'

  // Trigger metadata
  triggered_by: string // 'manual', 'refactor_it', 'daily_qa_scan', 'audit_it', 'celery_beat'
  triggered_by_session: string | null
  triggered_by_user: string | null
  trigger_context: Record<string, unknown>

  // Timing
  started_at: string
  completed_at: string | null
  duration_ms: number | null

  // Status
  status: 'running' | 'completed' | 'failed' | 'cancelled'
  error_message: string | null

  // Metrics
  metrics: Record<string, unknown>
  entries_found: number
  entries_saved: number

  // Comparison
  previous_scan_id: number | null
  metrics_delta: Record<string, unknown>

  created_at: string
}

export interface SparklineDataPoint {
  date: string // YYYY-MM-DD
  complexity: number | null
  scan_count: number
  high_priority_count: number
}

export interface SparklineData {
  dates: string[]
  complexity: (number | null)[]
  targets: number[]
  high_priority: number[]
}

export interface TriggerBreakdown {
  trigger: string
  count: number
  percentage: number
}

export interface ScanHistorySummary {
  total_scans: number
  avg_duration_ms: number | null
  complexity_trend: 'improving' | 'stable' | 'degrading' | 'unknown'
  most_active_trigger: string | null
  triggers_breakdown: TriggerBreakdown[]
}

export interface ScanHistoryResponse {
  scans: ScanHistoryEntry[]
  sparkline_data: SparklineData
  summary: ScanHistorySummary
}

export interface ScanComparison {
  before_scan: ScanHistoryEntry
  after_scan: ScanHistoryEntry
  before_metrics: Record<string, unknown>
  after_metrics: Record<string, unknown>
  delta: Record<string, unknown>
  delta_pct: Record<string, number>
}

// ============================================================================
// Scan History API Functions
// ============================================================================

/**
 * Fetch scan history for a project.
 *
 * @param projectId - Project to fetch history for
 * @param days - Number of days to look back (default: 30, max: 365)
 * @param scanType - Optional filter by scan type
 */
export async function fetchScanHistory(
  projectId: string,
  days: number = 30,
  scanType?: string,
): Promise<ScanHistoryResponse> {
  const params = new URLSearchParams()
  params.append('days', String(days))
  if (scanType) {
    params.append('scan_type', scanType)
  }

  const res = await fetch(
    `/api/projects/${projectId}/explorer/scan-history?${params}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch scan history' }))
    throw new Error(error.detail || 'Failed to fetch scan history')
  }
  return res.json()
}

/**
 * Fetch comparison between two scans.
 *
 * @param projectId - Project ID
 * @param before - Scan ID of the baseline scan
 * @param after - Scan ID of the comparison scan
 */
export async function fetchScanComparison(
  projectId: string,
  before: number,
  after: number,
): Promise<ScanComparison> {
  const params = new URLSearchParams()
  params.append('before', String(before))
  params.append('after', String(after))

  const res = await fetch(
    `/api/projects/${projectId}/explorer/scan-comparison?${params}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch scan comparison' }))
    throw new Error(error.detail || 'Failed to fetch scan comparison')
  }
  return res.json()
}
