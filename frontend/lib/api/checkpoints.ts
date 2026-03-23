/**
 * Checkpoints API client.
 *
 * Provides checkpoint information for dashboard and task detail views.
 */

import { buildQueryString, throwFromResponse } from './utils'

export interface BranchInfo {
  branch: string
  subtask_id: string
  type: 'task' | 'subtask'
}

export interface Checkpoint {
  task_id: string
  project_id: string
  snapshot_path: string
  base_branch: string
  created_at: string
  claimed_by: string
  size: string
  age: string
  branches: BranchInfo[]
}

/**
 * Get checkpoint details for a specific task.
 *
 * @param taskId - Task identifier
 * @param projectId - Optional project ID
 * @returns Checkpoint details
 */
export async function getCheckpoint(
  taskId: string,
  projectId?: string,
): Promise<Checkpoint | null> {
  const url = `/api/checkpoints/${taskId}${buildQueryString({ project_id: projectId })}`
  const response = await fetch(url)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    await throwFromResponse(response, 'Failed to fetch checkpoint')
  }

  return response.json()
}

/**
 * Get the active checkpoint for a project.
 *
 * @param projectId - Project identifier
 * @returns Active checkpoint or null
 */
export async function getActiveCheckpoint(
  projectId: string,
): Promise<Checkpoint | null> {
  const url = `/api/checkpoints/project/${projectId}/active`
  const response = await fetch(url)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    await throwFromResponse(response, 'Failed to fetch active checkpoint')
  }

  const text = await response.text()
  if (!text || text === 'null') {
    return null
  }

  return JSON.parse(text)
}
