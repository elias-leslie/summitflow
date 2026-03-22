/**
 * Tasks API - Enrichment & Refinement Workflow
 */

import { fetchWithErrorHandling, patchJson, postJson } from './utils'
import type {
  Task,
  EnrichmentRequest,
  DiscussionResponse,
  SubtasksResponse,
  Subtask,
  Step,
} from './tasks-types'

// ============================================================================
// Enrichment Workflow
// ============================================================================

/**
 * Enrich a task with AI-generated objective, criteria, and subtasks.
 * @param sync If true, runs enrichment synchronously and returns enriched task.
 *             If false (default), queues enrichment and returns task with status 'enriching'.
 */
export async function enrichTask(
  projectId: string,
  request: EnrichmentRequest,
  sync = false,
): Promise<Task> {
  const url = `/api/projects/${projectId}/tasks/enrich${sync ? '?sync=true' : ''}`
  return postJson(url, request, 'Failed to enrich task')
}

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
// Steps
// ============================================================================

/**
 * Get steps for a subtask from the normalized table.
 */
export async function getSteps(
  projectId: string,
  taskId: string,
  subtaskId: string,
): Promise<Step[]> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps`,
    {
      errorMessage: 'Failed to fetch steps',
    },
  )
}

/**
 * Update a step's passes status.
 */
export async function updateStep(
  projectId: string,
  taskId: string,
  subtaskId: string,
  stepNumber: number,
  passes: boolean,
): Promise<Step> {
  return patchJson(
    `/api/projects/${projectId}/tasks/${taskId}/subtasks/${subtaskId}/steps/${stepNumber}`,
    { passes },
    'Failed to update step',
  )
}

// ============================================================================
// Acceptance Criteria
// ============================================================================


