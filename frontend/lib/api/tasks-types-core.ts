/**
 * Tasks API - Core Type Definitions
 */

// ============================================================================
// Task Core Types
// ============================================================================

export type TaskStatus =
  | 'pending'
  | 'running'
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

export type TaskExecutionMode = 'manual' | 'autonomous' | 'manual_only'

export type EnrichmentStatus =
  | 'none'
  | 'draft'
  | 'enriching'
  | 'review'
  | 'discussing'
  | 'accepted'
  | 'failed'

export interface TaskAcceptanceCriterion {
  id: string
  criterion_id?: string
  criterion: string
  category?: 'performance' | 'correctness' | 'security' | 'quality'
  measurement?: string
  threshold?: string | null
  verify_by?: 'test' | 'opus' | 'human' | 'agent'
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

export interface VerificationResult {
  execution_clean?: boolean
  subtask_count?: number
  total_self_fix_attempts?: number
  total_supervisor_attempts?: number
  total_extensions_granted?: number
  // Partial merge fields
  partial_merge?: boolean
  passed_count?: number
  failed_count?: number
  failed_subtasks?: string[]
  failed_details?: { subtask_id: string; failure_reason: string }[]
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
  total_sessions: number
  total_tokens_used: number
  created_at: string | null
  updated_at: string | null
  started_at: string | null
  completed_at: string | null
  priority: number
  labels: string[]
  task_type: TaskType
  parent_task_id: string | null
  capability?: CapabilityContext | null
  blockers?: BlockerInfo[] | null
  blocked_by_incomplete?: boolean | null
  // Pipeline v2 fields
  done_when?: string[] | null
  acceptance_criteria?: TaskAcceptanceCriterion[] | null
  current_phase?: 'plan' | 'implement' | 'test' | 'verify' | 'complete' | null
  verification_result?: VerificationResult | null
  // Enrichment fields
  raw_request?: string | null
  enrichment_status?: EnrichmentStatus | null
  enriched_by?: string | null
  enriched_at?: string | null
  execution_mode?: TaskExecutionMode
  // Autonomous execution flag
  autonomous?: boolean
  // Agent override for autonomous execution
  agent_override?: string | null
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
