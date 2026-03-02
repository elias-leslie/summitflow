/**
 * Tasks API - Agent Hub Type Definitions
 */

// ============================================================================
// Agent Hub Types
// ============================================================================

export interface CodingAgent {
  slug: string
  name: string
  description: string | null
  is_coding_agent: boolean
}

export interface CodingAgentsResponse {
  agents: CodingAgent[]
  total: number
}

export type AgentEventType =
  | 'user_message'
  | 'assistant_message'
  | 'system_message'
  | 'thinking'
  | 'tool_use'
  | 'tool_result'
  | 'memory_inject'
  | 'memory_cite'
  | 'error'

export interface AgentHubEvent {
  id: string
  session_id: string | null
  session_index: number
  turn: number
  sequence: number
  event_type: AgentEventType
  role: string | null
  content: string | null
  tool_name: string | null
  tool_input: Record<string, unknown> | null
  tool_output: Record<string, unknown> | null
  tokens: number | null
  duration_ms: number | null
  model_used: string | null
  agent_id: string | null
  agent_name: string | null
  created_at: string
}

export interface AgentHubEventsResponse {
  task_id: string
  session_ids: string[]
  events: AgentHubEvent[]
  total: number
  max_turn: number
}
