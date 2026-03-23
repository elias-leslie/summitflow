/**
 * Tasks API - Agent Hub Integration & Observability
 */

import { getAgentHubProxyBase } from '../agent-hub-proxy'
import { getApiBaseUrl } from '../api-config'
import { buildQueryString, fetchWithErrorHandling } from './utils'
import type {
  CodingAgentsResponse,
  AgentEventType,
  AgentHubEventsResponse,
  NarrationTimelineResponse,
} from './tasks-types'

// ============================================================================
// Coding Agents
// ============================================================================

/**
 * Fetch coding agents from Agent Hub (via SummitFlow proxy).
 * These are agents that can execute autonomous tasks.
 */
export async function fetchCodingAgents(): Promise<CodingAgentsResponse> {
  const apiBase = typeof window === 'undefined' ? getApiBaseUrl() : getAgentHubProxyBase()
  return fetchWithErrorHandling<CodingAgentsResponse>(`${apiBase}/agents`, {
    errorMessage: 'Failed to fetch coding agents',
  })
}

// ============================================================================
// Agent Observability
// ============================================================================

/**
 * Fetch Agent Hub session events for a task.
 * Returns full observability data including thinking, tool calls, memory events.
 */
export async function fetchTaskAgentEvents(
  projectId: string,
  taskId: string,
  options?: {
    event_type?: AgentEventType
    turn?: number
    page?: number
    page_size?: number
  },
): Promise<AgentHubEventsResponse> {
  const pageSize = options?.page_size ?? 500
  let page = options?.page ?? 1
  let allEvents: AgentHubEventsResponse['events'] = []
  let latestResponse: AgentHubEventsResponse | null = null

  while (true) {
    const query = buildQueryString({
      event_type: options?.event_type,
      turn: options?.turn,
      page,
      page_size: pageSize,
    })

    latestResponse = await fetchWithErrorHandling(
      `/api/projects/${projectId}/tasks/${taskId}/agent-events${query}`,
      {
        errorMessage: 'Failed to fetch agent events',
      },
    )

    if (!latestResponse) {
      throw new Error('Failed to fetch agent events')
    }

    const responsePage = latestResponse
    allEvents = allEvents.concat(responsePage.events)
    if (
      responsePage.events.length < pageSize ||
      allEvents.length >= responsePage.total
    ) {
      break
    }
    page += 1
  }

  return {
    ...latestResponse,
    events: allEvents,
  }
}

// ============================================================================
// Narration Timeline
// ============================================================================

export async function fetchNarrationTimeline(
  taskId: string,
  options?: { tag_type?: string; limit?: number },
): Promise<NarrationTimelineResponse> {
  const proxyBase = getAgentHubProxyBase()
  const query = buildQueryString({
    tag_type: options?.tag_type,
    limit: options?.limit,
  })
  return fetchWithErrorHandling<NarrationTimelineResponse>(
    `${proxyBase}/narration/tasks/${taskId}${query}`,
    { errorMessage: 'Failed to fetch narration timeline' },
  )
}
