/**
 * Explorer Analysis API - Coverage gaps and refactor targets.
 *
 * Extracted from explorer.ts to reduce file size and improve modularity.
 */

import { buildQueryString, fetchWithErrorHandling } from './utils'

// ============================================================================
// Types
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
  priority: 'high' | 'medium' | 'none'
  reason: string
  hotspot_score: number
  commit_count_90d: number
  test_file_exists: boolean
  complexity_method: 'radon' | 'heuristic'
  health_flags: string[]
  refactor_issues: string[]
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
// API Functions
// ============================================================================

/**
 * Fetch coverage gaps (uncovered endpoints, pages, tables).
 */
export async function fetchCoverageGaps(
  projectId: string,
): Promise<CoverageGapsResponse> {
  return fetchWithErrorHandling<CoverageGapsResponse>(
    `/api/projects/${projectId}/analysis/coverage-gaps`,
    { errorMessage: 'Failed to fetch coverage gaps' },
  )
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
  const query = buildQueryString({
    code_only: options.codeOnly ?? true,
    extensions: options.extensions,
    limit: options.limit,
  })
  return fetchWithErrorHandling<RefactorTargetsResponse>(
    `/api/projects/${projectId}/explorer/refactor-targets${query}`,
    { errorMessage: 'Failed to fetch refactor targets' },
  )
}
