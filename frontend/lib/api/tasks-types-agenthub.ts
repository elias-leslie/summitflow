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

export interface AgentHubLiveActivity {
  phase: string
  status: string
  summary?: string | null
  health: string
  stalled: boolean
  stall_reason?: string | null
  quiet_for_seconds?: number | null
  current_tool_name?: string | null
  last_tool_name?: string | null
  last_read_path?: string | null
  last_write_path?: string | null
  last_command?: string | null
  last_validation_command?: string | null
  last_command_exit_code?: number | null
  outstanding_tool_calls: number
  tool_calls_count: number
  termination_reason?: string | null
  files_touched: string[]
}

export interface AgentHubSessionSummary {
  id: string
  status: string
  agent_slug: string | null
  requested_model?: string | null
  effective_model?: string | null
  requested_provider?: string | null
  effective_provider?: string | null
  fallback_used: boolean
  fallback_reason?: string | null
  updated_at: string
  live_activity?: AgentHubLiveActivity | null
}

export interface AgentHubEventsResponse {
  task_id: string
  session_ids: string[]
  sessions: AgentHubSessionSummary[]
  events: AgentHubEvent[]
  total: number
  max_turn: number
}

// ============================================================================
// Narration Tags
// ============================================================================

export type NarrationTagType =
  | 'started'
  | 'found'
  | 'modified'
  | 'tested'
  | 'confidence'
  | 'blocked'
  | 'decision'

export interface NarrationTag {
  id: number
  task_id: string
  session_id: string
  tag_type: NarrationTagType
  content: string
  created_at: string
}

export interface NarrationTimelineResponse {
  task_id: string
  tags: NarrationTag[]
  total: number
}
