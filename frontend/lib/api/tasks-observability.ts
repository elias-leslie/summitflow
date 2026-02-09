/**
 * Tasks API - Agent Hub Integration & Observability
 */

import { fetchWithErrorHandling, getApiBase } from './utils'
import type {
  CodingAgentsResponse,
  AgentEventType,
  AgentHubEventsResponse,
} from './tasks-types'

// ============================================================================
// Coding Agents
// ============================================================================

/**
 * Fetch coding agents from Agent Hub (via SummitFlow proxy).
 * These are agents that can execute autonomous tasks.
 */
export async function fetchCodingAgents(): Promise<CodingAgentsResponse> {
  const apiBase = getApiBase()
  const response = await fetch(`${apiBase}/api/agent-hub/agents`)
  if (!response.ok) {
    throw new Error('Failed to fetch coding agents')
  }
  return response.json()
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
  const params = new URLSearchParams()
  if (options?.event_type) params.set('event_type', options.event_type)
  if (options?.turn !== undefined) params.set('turn', options.turn.toString())
  if (options?.page) params.set('page', options.page.toString())
  if (options?.page_size) params.set('page_size', options.page_size.toString())

  const query = params.toString() ? `?${params.toString()}` : ''

  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/agent-events${query}`,
    {
      errorMessage: 'Failed to fetch agent events',
    },
  )
}
