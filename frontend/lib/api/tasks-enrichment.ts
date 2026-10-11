/**
 * Tasks API - Enrichment & Refinement Workflow
 */

import type {
  DiscussionResponse,
  Subtask,
  SubtasksResponse,
  Task,
} from './tasks-types'
import { fetchWithErrorHandling, patchJson, postJson } from './utils'

// ============================================================================
// Enrichment Workflow
// ============================================================================

/**
 * Send a message to discuss and refine a task with the AI.
 */
export async function discussTask(
  projectId: string,
  taskId: string,
  message: string,
): Promise<DiscussionResponse> {
  return postJson(
    `/api/projects/${projectId}/tasks/${taskId}/discuss`,
    { message },
    'Failed to discuss task',
  )
}

/**
 * Accept an enriched task, moving it to 'pending' status for execution.
 */
export async function acceptTask(
  projectId: string,
  taskId: string,
): Promise<Task> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/accept`,
    {
      method: 'POST',
      errorMessage: 'Failed to accept task',
    },
  )
}

// ============================================================================
// Subtasks
// ============================================================================

/**
 * Get subtasks for a task.
 */
export async function getSubtasks(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks`,
    {
      errorMessage: 'Failed to fetch subtasks',
    },
  )
}

/**
 * Get subtasks with steps included.
 */
export async function getSubtasksWithSteps(
  projectId: string,
  taskId: string,
): Promise<SubtasksResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks?include_steps=true`,
    {
      errorMessage: 'Failed to fetch subtasks with steps',
    },
  )
}

/**
 * Update a subtask's passes status.
 */
export async function updateSubtask(
  projectId: string,
  taskId: string,
  subtaskId: string,
  passes: boolean,
): Promise<Subtask> {
  return patchJson(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}`,
    { passes },
    'Failed to update subtask',
  )
}

// ============================================================================
// Acceptance Criteria
// ============================================================================
