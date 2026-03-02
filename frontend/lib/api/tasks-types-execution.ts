/**
 * Tasks API - Execution Type Definitions
 */

import type { Task, TaskType } from './tasks-types-core'

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
