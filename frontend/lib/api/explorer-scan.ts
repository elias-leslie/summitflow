/**
 * Explorer Scan API - Scan operations, history, and comparisons.
 *
 * Extracted from explorer.ts to reduce file size and improve modularity.
 */

import { buildQueryString, fetchWithErrorHandling } from './utils'
import type { ExplorerEntryType } from './explorer'

// ============================================================================
// Types
// ============================================================================

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

export interface ScanHistoryEntry {
  id: number
  project_id: string
  scan_type: string // 'file', 'page', 'endpoint', 'database', 'task', 'full'

  // Trigger metadata
  triggered_by: 'manual' | 'scheduled' | 'project_create' | 'refactor_it' | 'audit_it'
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

// ============================================================================
// API Functions
// ============================================================================

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
  const query = buildQueryString({ type })
  return fetchWithErrorHandling<ScanResponse>(
    `/api/projects/${projectId}/explorer/scan${query}`,
    {
      method: 'POST',
      errorMessage: 'Failed to trigger scan',
    },
  )
}

/**
 * Get current scan status for polling.
 *
 * @param projectId - Project to check
 */
export async function fetchScanStatus(
  projectId: string,
): Promise<ScanStatusResponse> {
  return fetchWithErrorHandling<ScanStatusResponse>(
    `/api/projects/${projectId}/explorer/scan/status`,
    { errorMessage: 'Failed to fetch scan status' },
  )
}

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
  const query = buildQueryString({
    days,
    scan_type: scanType,
  })
  return fetchWithErrorHandling<ScanHistoryResponse>(
    `/api/projects/${projectId}/explorer/scan-history${query}`,
    { errorMessage: 'Failed to fetch scan history' },
  )
}

