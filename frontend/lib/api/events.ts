/**
 * Events API Client
 *
 * API client for the unified events table endpoints.
 * Follows existing patterns from lib/api/explorer.ts.
 */

// ============================================================================
// Types - Aligned with backend Event schema
// ============================================================================

export type EventLevel = 'error' | 'warning' | 'info' | 'debug'
export type EventVisibility = 'user' | 'internal' | 'debug'

export interface Event {
  id: string
  project_id: string
  trace_id: string
  span_id: string | null
  parent_span_id: string | null
  event_type: string
  name: string | null
  source: string
  level: EventLevel
  visibility: EventVisibility
  message: string | null
  attributes: Record<string, unknown>
  timestamp: string
}

export interface EventsQueryResult {
  events: Event[]
  total: number
  summary: Record<string, number>
}

// ============================================================================
// Filter Types
// ============================================================================

export interface EventFilters {
  trace_id?: string
  source?: string
  level?: EventLevel
  visibility?: EventVisibility
  search?: string
  limit?: number
  offset?: number
}

// ============================================================================
// API Functions
// ============================================================================

/**
 * Fetch events for a project with optional filters.
 */
export async function getEvents(
  projectId: string,
  filters: EventFilters = {},
): Promise<EventsQueryResult> {
  const params = new URLSearchParams()

  if (filters.trace_id) params.append('trace_id', filters.trace_id)
  if (filters.source) params.append('source', filters.source)
  if (filters.level) params.append('level', filters.level)
  if (filters.visibility) params.append('visibility', filters.visibility)
  if (filters.search) params.append('search', filters.search)
  if (filters.limit !== undefined)
    params.append('limit', filters.limit.toString())
  if (filters.offset !== undefined)
    params.append('offset', filters.offset.toString())

  const queryString = params.toString()
  const res = await fetch(
    `/api/projects/${projectId}/events${queryString ? `?${queryString}` : ''}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch events' }))
    throw new Error(error.detail || 'Failed to fetch events')
  }
  return res.json()
}

/**
 * Fetch events for a specific task by trace_id.
 * Convenience wrapper around getEvents with trace_id filter.
 */
export async function getEventsByTask(
  projectId: string,
  taskId: string,
  options: {
    visibility?: EventVisibility
    limit?: number
  } = {},
): Promise<Event[]> {
  const result = await getEvents(projectId, {
    trace_id: taskId,
    visibility: options.visibility,
    limit: options.limit,
  })
  return result.events
}
