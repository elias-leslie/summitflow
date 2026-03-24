/**
 * Feedback API - Agent Hub integration for agent feedback system.
 * Routes through Next.js proxy: /api/agent-hub/feedback/* -> Agent Hub port 8003
 */

import { getAgentHubProxyBase } from '../agent-hub-proxy'
import { buildQueryString, deleteJson, fetchWithErrorHandling, patchJson } from './utils'

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
  status: 'open' | 'acknowledged' | 'resolved' | 'wont_fix' | 'archived'
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

export type FeedbackStatus = FeedbackItem['status']
export type FeedbackStatusFilter = 'active' | FeedbackStatus

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

/** Raw shape from Agent Hub API */
interface FeedbackSummaryRaw {
  total_items: number
  counts_by_type_status: { feedback_type: string; status: string; count: number }[]
  top_unresolved: {
    id: string; component_id: string; feedback_type: string;
    title: string; vote_count: number; status: string; created_at: string;
  }[]
  by_component: {
    component_id: string; open_count: number; resolved_count: number;
    wont_fix_count: number; archived_count: number;
    friction_count: number; idea_count: number; praise_count: number; total_votes: number;
  }[]
}

/** Per-component breakdown with type counts for health visualization */
export interface ComponentBreakdown {
  total: number
  open: number
  friction: number
  idea: number
  praise: number
}

/** Transformed shape used by frontend components */
export interface FeedbackSummary {
  total: number
  by_type: Record<string, number>
  by_status: Record<string, number>
  top_unresolved: FeedbackSummaryRaw['top_unresolved']
  by_component: Record<string, ComponentBreakdown>
}

/** Transform raw API response into frontend-friendly shape */
function transformSummary(raw: FeedbackSummaryRaw): FeedbackSummary {
  const by_type: Record<string, number> = {}
  const by_status: Record<string, number> = {}
  for (const row of raw.counts_by_type_status) {
    by_type[row.feedback_type] = (by_type[row.feedback_type] ?? 0) + row.count
    by_status[row.status] = (by_status[row.status] ?? 0) + row.count
  }
  const by_component: Record<string, ComponentBreakdown> = {}
  for (const c of raw.by_component) {
    by_component[c.component_id] = {
      total: c.open_count + c.resolved_count + c.wont_fix_count + c.archived_count,
      open: c.open_count,
      friction: c.friction_count ?? 0,
      idea: c.idea_count ?? 0,
      praise: c.praise_count ?? 0,
    }
  }
  return {
    total: raw.total_items,
    by_type,
    by_status,
    top_unresolved: raw.top_unresolved,
    by_component,
  }
}

export interface FeedbackFilters {
  query?: string
  component_id?: string
  feedback_type?: string
  status?: FeedbackStatusFilter
  project_id?: string
  sort?: 'votes' | 'newest' | 'oldest'
  limit?: number
  offset?: number
}

// ============================================================================
// API Functions
// ============================================================================

function feedbackUrl(path: string): string {
  return `${getAgentHubProxyBase()}/feedback${path}`
}

/**
 * List/search feedback items with filters.
 */
export async function fetchFeedbackItems(
  filters: FeedbackFilters = {},
): Promise<FeedbackListResponse> {
  const query = buildQueryString(filters as Record<string, string | number | undefined>)
  return fetchWithErrorHandling<FeedbackListResponse>(feedbackUrl(query), {
    errorMessage: 'Failed to fetch feedback items',
  })
}

/**
 * Get a single feedback item with votes.
 */
export async function fetchFeedbackItem(id: string): Promise<FeedbackItemWithVotes> {
  return fetchWithErrorHandling<FeedbackItemWithVotes>(feedbackUrl(`/${id}`), {
    errorMessage: 'Failed to fetch feedback item',
  })
}

/**
 * Get aggregated feedback summary.
 */
export async function fetchFeedbackSummary(
  projectId?: string,
): Promise<FeedbackSummary> {
  const query = buildQueryString({ project_id: projectId })
  const raw = await fetchWithErrorHandling<FeedbackSummaryRaw>(feedbackUrl(`/summary${query}`), {
    errorMessage: 'Failed to fetch feedback summary',
  })
  return transformSummary(raw)
}

/**
 * Update feedback item status (resolve, acknowledge, etc.)
 */
export async function updateFeedbackStatus(
  id: string,
  data: {
    status: FeedbackStatus
    resolution_note?: string
    linked_task_id?: string
  },
): Promise<FeedbackItem> {
  return patchJson<FeedbackItem>(feedbackUrl(`/${id}`), data, 'Failed to update feedback status')
}

/**
 * Delete a feedback item and all its votes.
 */
export async function deleteFeedbackItem(
  id: string,
): Promise<{ deleted: boolean; id: string }> {
  return deleteJson<{ deleted: boolean; id: string }>(feedbackUrl(`/${id}`), 'Failed to delete feedback item')
}
