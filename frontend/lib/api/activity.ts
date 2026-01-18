/**
 * Activity API - Unified activity feed for dashboard.
 */

import { buildQueryString, fetchWithErrorHandling } from './utils'

export type ActivityEventType = 'task' | 'session' | 'backup' | 'git'

export interface ActivityEvent {
  type: ActivityEventType
  message: string
  timestamp: string | null
  project_id: string
  metadata: {
    task_id?: string
    session_id?: string
    backup_id?: string
    commit_sha?: string
    status?: string
    title?: string
    agent_type?: string
    backup_type?: string
    size_bytes?: number
    tests_passed?: number
    tests_failed?: number
    notes?: string
  }
}

export interface ActivityFeedResponse {
  items: ActivityEvent[]
  total: number
  limit: number
  offset: number
  has_more: boolean
}

export interface FetchActivityOptions {
  project_id?: string
  limit?: number
  offset?: number
  types?: ActivityEventType[]
}

/**
 * Fetch activity feed from the API.
 */
export async function fetchActivity(
  options: FetchActivityOptions = {},
): Promise<ActivityFeedResponse> {
  const query = buildQueryString({
    project_id: options.project_id,
    limit: options.limit ?? 50,
    offset: options.offset,
    types: options.types?.join(','),
  })

  return fetchWithErrorHandling<ActivityFeedResponse>(`/api/activity${query}`, {
    errorMessage: 'Failed to fetch activity feed',
  })
}
