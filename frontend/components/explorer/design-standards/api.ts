/**
 * API functions for fetching design standards
 */

import { fetchWithErrorHandling } from '@/lib/api/utils'

import type { DesignRule } from './types'

/**
 * Fetch effective design rules for a project
 * Falls back to base rules if project has no standard configured
 * Uses relative URLs for CF Access compatibility
 */
export async function fetchEffectiveRules(
  projectId: string,
): Promise<DesignRule[]> {
  try {
    return await fetchWithErrorHandling<DesignRule[]>(
      `/api/projects/${projectId}/design-standards/effective-rules`,
      { errorMessage: 'Failed to fetch project design rules' },
    )
  } catch {
    // Fallback to base rules if project has no standard
    return fetchWithErrorHandling<DesignRule[]>(
      '/api/design-standards/base/rules',
      { errorMessage: 'Failed to fetch design rules' },
    )
  }
}
