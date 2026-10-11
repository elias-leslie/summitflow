/**
 * Tasks API - Subtasks
 */

import type { Subtask, SubtasksResponse } from './tasks-types'
import { fetchWithErrorHandling, patchJson } from './utils'

// ============================================================================
// Subtasks
// ============================================================================

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
