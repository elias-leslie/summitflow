/**
 * API functions for code health monitoring
 */

export interface RefactorTarget {
  path: string
  name: string
  complexity_score: number
  lines_of_code: number
  function_count: number
  class_count: number
  priority: 'high' | 'medium' | 'none'
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

/**
 * Fetch refactor targets from API
 * Uses relative URLs for CF Access compatibility
 */
export async function fetchRefactorTargets(
  projectId: string,
  codeOnly: boolean = true,
): Promise<RefactorTargetsResponse> {
  const params = new URLSearchParams({ code_only: String(codeOnly) })
  const res = await fetch(
    `/api/projects/${projectId}/explorer/refactor-targets?${params}`,
  )
  if (!res.ok) {
    throw new Error('Failed to fetch refactor targets')
  }
  return res.json()
}
