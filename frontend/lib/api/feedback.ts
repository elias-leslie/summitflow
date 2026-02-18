/**
 * Feedback API - Agent Hub integration for agent feedback system.
 * Routes through Next.js proxy: /api/agent-hub/feedback/* -> Agent Hub port 8003
 */

import { buildQueryString, getApiBase } from './utils'

// ============================================================================
// Types
// ============================================================================

export interface FeedbackItem {
  id: string
  component_id: string
  feedback_type: 'friction' | 'idea' | 'improvement' | 'praise'
  title: string
  description: string | null
  severity: string | null
  status: 'open' | 'acknowledged' | 'resolved' | 'wont_fix'
  project_id: string
  agent_slug: string | null
  model_used: string | null
  session_type: string | null
  vote_count: number
  linked_task_id: string | null
  resolved_at: string | null
  resolution_note: string | null
  created_at: string
  updated_at: string
}

export interface FeedbackVote {
  id: string
  feedback_item_id: string
  session_id: string
  comment: string | null
  agent_slug: string | null
  model_used: string | null
  created_at: string
}

export interface FeedbackItemWithVotes extends FeedbackItem {
  votes: FeedbackVote[]
}

export interface FeedbackListResponse {
  items: FeedbackItem[]
  total: number
}

export interface FeedbackSummary {
  total: number
  by_type: Record<string, number>
  by_status: Record<string, number>
  top_unresolved: FeedbackItem[]
  by_component: Record<string, { total: number; open: number }>
}

export interface ComponentFeedback {
  component_id: string
  total: number
  open: number
  items: FeedbackItem[]
}

export interface FeedbackFilters {
  query?: string
  component_id?: string
  feedback_type?: string
  status?: string
  project_id?: string
  sort?: 'votes' | 'newest' | 'oldest'
  limit?: number
  offset?: number
}

// ============================================================================
// API Functions
// ============================================================================

async function feedbackFetch<T>(path: string, options?: RequestInit): Promise<T> {
  const apiBase = getApiBase()
  const response = await fetch(`${apiBase}/api/agent-hub/feedback${path}`, options)
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'Request failed' }))
    throw new Error(error.detail || error.message || 'Request failed')
  }
  return response.json()
}

/**
 * List/search feedback items with filters.
 */
export async function fetchFeedbackItems(
  filters: FeedbackFilters = {},
): Promise<FeedbackListResponse> {
  const query = buildQueryString(filters as Record<string, string | number | undefined>)
  return feedbackFetch<FeedbackListResponse>(`${query}`)
}

/**
 * Get a single feedback item with votes.
 */
export async function fetchFeedbackItem(id: string): Promise<FeedbackItemWithVotes> {
  return feedbackFetch<FeedbackItemWithVotes>(`/${id}`)
}

/**
 * Get aggregated feedback summary.
 */
export async function fetchFeedbackSummary(
  projectId?: string,
): Promise<FeedbackSummary> {
  const query = buildQueryString({ project_id: projectId })
  return feedbackFetch<FeedbackSummary>(`/summary${query}`)
}

/**
 * Get feedback for a specific component.
 */
export async function fetchComponentFeedback(
  componentId: string,
  status?: string,
): Promise<ComponentFeedback> {
  const query = buildQueryString({ status })
  return feedbackFetch<ComponentFeedback>(`/components/${componentId}${query}`)
}

/**
 * Update feedback item status (resolve, acknowledge, etc.)
 */
export async function updateFeedbackStatus(
  id: string,
  data: {
    status: string
    resolution_note?: string
    linked_task_id?: string
  },
): Promise<FeedbackItem> {
  return feedbackFetch<FeedbackItem>(`/${id}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
}
