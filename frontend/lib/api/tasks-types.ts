/**
 * Tasks API - Type Definitions
 */

// ============================================================================
// Task Core Types
// ============================================================================

export type TaskStatus =
  | 'pending'
  | 'queue'
  | 'running'
  | 'paused'
  | 'blocked'
  | 'pr_created'
  | 'ai_reviewing'
  | 'completed'
  | 'failed'
  | 'cancelled'

export type TaskType =
  | 'feature'
  | 'bug'
  | 'task'
  | 'refactor'
  | 'debt'
  | 'regression'

export type AgentType = 'claude' | 'gemini'

export interface TaskAcceptanceCriterion {
  id: string
  criterion_id?: string
  criterion: string
  category?: 'performance' | 'correctness' | 'security' | 'quality'
  measurement?: string
  threshold?: string | null
  verify_command?: string | null
  verify_by?: 'test' | 'opus' | 'human' | 'agent'
  expected_output?: string | null
  test_file?: string | null
  test_name?: string | null
  verified: boolean
  verified_at?: string | null
  verified_by_who?: 'opus' | 'test' | 'human' | 'agent' | null
}

export interface CapabilityContext {
  id: number
  capability_id: string
  name: string
  criteria_passed: number
  criteria_total: number
  acceptance_criteria?: TaskAcceptanceCriterion[] | null
}

export interface BlockerInfo {
  id: string
  title: string
  status: string
  priority: number
}

export interface WorktreeInfo {
  path: string
  branch: string
  is_active: boolean
}

export interface Task {
  id: string
  project_id: string
  capability_id: number | null
  title: string
  description: string | null
  status: TaskStatus
  plan_content: Record<string, unknown> | null
  progress_log: string | null
  error_message: string | null
  branch_name: string | null
  commits: string[]
  pull_request_url: string | null
  total_sessions: number
  total_tokens_used: number
  created_at: string | null
  started_at: string | null
  completed_at: string | null
  priority: number
  labels: string[]
  task_type: TaskType
  parent_task_id: string | null
  capability?: CapabilityContext | null
  blockers?: BlockerInfo[] | null
  blocked_by_incomplete?: boolean | null
  // AI agent reliability fields
  objective?: string | null
  acceptance_criteria?: TaskAcceptanceCriterion[] | null
  current_phase?: 'plan' | 'implement' | 'test' | 'verify' | 'complete' | null
  verification_result?: Record<string, unknown> | null
  // Enrichment fields
  raw_request?: string | null
  enrichment_status?: EnrichmentStatus | null
  enriched_by?: string | null
  enriched_at?: string | null
  // Autonomous execution flag
  autonomous?: boolean
  // Agent override for autonomous execution
  agent_override?: string | null
  // Worktree info (when task has an active worktree)
  worktree?: WorktreeInfo | null
  // Agent Hub session IDs for full observability
  agent_hub_session_ids?: string[]
}

export interface TaskListResponse {
  tasks: Task[]
  total: number
}

export interface TaskDependency {
  id: number
  task_id: string
  depends_on_task_id: string
  dependency_type: string
  created_at: string | null
  depends_on_title?: string
  depends_on_status?: string
}

export interface StartTaskResult {
  status: string
  task_id: string
}

// ============================================================================
// Enrichment Types
// ============================================================================

export type EnrichmentStatus =
  | 'none'
  | 'draft'
  | 'enriching'
  | 'review'
  | 'discussing'
  | 'accepted'
  | 'failed'

export interface Step {
  id: number
  subtask_id: string
  step_number: number
  description: string
  spec: Record<string, unknown> | null
  passes: boolean
  passed_at: string | null
  created_at: string | null
}

export interface StepSummary {
  total: number
  completed: number
  progress_percent: number
}

export interface Subtask {
  id: string
  task_id: string
  subtask_id: string
  phase: string
  description: string
  steps: string[] // JSONB array (legacy)
  steps_from_table?: Step[] // Normalized table steps (when include_steps=true)
  step_summary?: StepSummary // Step completion summary (when include_steps=true)
  passes: boolean
  passed_at: string | null
  display_order: number
  created_at: string | null
}

export interface SubtasksResponse {
  subtasks: Subtask[]
  total: number
  completed: number
  next_subtask_id: string | null
}

export interface EnrichmentRequest {
  raw_request: string
  priority?: number
  task_type?: TaskType
}

export interface CleanupPromptResponse {
  cleaned_prompt: string
  changes_made: string[]
}

export interface DiscussionMessage {
  role: 'user' | 'assistant'
  content: string
  timestamp: string
}

export interface DiscussionResponse {
  response: string
  updated_task: Task | null
  history: DiscussionMessage[]
}

export interface CriterionVerifyRequest {
  verified?: boolean
  verified_by: 'test' | 'opus' | 'human' | 'agent'
}

export interface CriterionVerifyResponse {
  status: string
  task_id: string
  criterion_id: string
  verified_by: string
}

// ============================================================================
// Execution Types
// ============================================================================

export interface ExecuteTaskOptions {
  model?: string
}

export interface ExecuteTaskResponse {
  execution_id: string
  task_id: string
  status: string
}

export interface BatchTaskCreateItem {
  title: string
  description?: string
  capability_id?: number
  priority?: number
  labels?: string[]
  task_type?: TaskType
  parent_task_id?: string
  objective?: string
}

export interface BatchTaskResult {
  title: string
  success: boolean
  id?: string
  error?: string
}

export interface BatchTaskResponse {
  created: Task[]
  errors: BatchTaskResult[]
}

export interface DeleteTaskResponse {
  status: string
  project_id: string
  task_id: string
}

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
