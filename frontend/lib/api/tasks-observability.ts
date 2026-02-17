/**
 * Tasks API - Agent Hub Integration & Observability
 */

import { buildQueryString, fetchWithErrorHandling, getApiBase } from './utils'
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
  const query = buildQueryString({
    event_type: options?.event_type,
    turn: options?.turn,
    page: options?.page,
    page_size: options?.page_size,
  })

  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/agent-events${query}`,
    {
      errorMessage: 'Failed to fetch agent events',
    },
  )
}
