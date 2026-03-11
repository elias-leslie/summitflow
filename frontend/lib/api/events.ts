/**
 * Events API Client
 *
 * API client for the unified events table endpoints.
 * Follows existing patterns from lib/api/explorer.ts.
 */

import { buildQueryString } from './utils'

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
  after?: string
  event_type?: string
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
  const query = buildQueryString({
    trace_id: filters.trace_id,
    source: filters.source,
    level: filters.level,
    visibility: filters.visibility,
    search: filters.search,
    after: filters.after,
    event_type: filters.event_type,
    limit: filters.limit,
    offset: filters.offset,
  })

  const res = await fetch(
    `/api/projects/${projectId}/events${query}`,
  )
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch events' }))
    throw new Error(error.detail || 'Failed to fetch events')
  }
  return res.json()
}

export async function getEventsForTrace(
  projectId: string,
  traceId: string,
  options: {
    visibility?: EventVisibility
    level?: EventLevel
    after?: string
    limit?: number
  } = {},
): Promise<Event[]> {
  const query = buildQueryString({
    visibility: options.visibility,
    level: options.level,
    after: options.after,
    limit: options.limit,
  })

  const res = await fetch(`/api/projects/${projectId}/events/by-trace/${traceId}${query}`)
  if (!res.ok) {
    const error = await res
      .json()
      .catch(() => ({ detail: 'Failed to fetch trace events' }))
    throw new Error(error.detail || 'Failed to fetch trace events')
  }

  const result = (await res.json()) as { events: Event[] }
  return result.events
}
