/**
 * Tasks API - Execution Type Definitions
 */

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

export interface DeleteTaskResponse {
  status: string
  project_id: string
  task_id: string
}
