/**
 * API functions for fetching design standards
 */

import type { DesignRule } from './types'

/**
 * Fetch effective design rules for a project
 * Falls back to base rules if project has no standard configured
 * Uses relative URLs for CF Access compatibility
 */
export async function fetchEffectiveRules(
  projectId: string,
): Promise<DesignRule[]> {
  const res = await fetch(
    `/api/projects/${projectId}/design-standards/effective-rules`,
  )
  if (!res.ok) {
    // Fallback to base rules if project has no standard
    const baseRes = await fetch('/api/design-standards/base/rules')
    if (!baseRes.ok) throw new Error('Failed to fetch design rules')
    return baseRes.json()
  }
  return res.json()
}
