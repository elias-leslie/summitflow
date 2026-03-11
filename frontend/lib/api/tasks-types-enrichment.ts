/**
 * Tasks API - Enrichment Type Definitions
 */

import type { Task, TaskType } from './tasks-types-core'

// ============================================================================
// Enrichment Types
// ============================================================================

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