/**
 * Checkpoints API client.
 *
 * Provides checkpoint information for dashboard and task detail views.
 */

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

export interface CheckpointsListResponse {
  checkpoints: Checkpoint[]
  total: number
}

/**
 * List all active checkpoints.
 *
 * @param projectId - Optional filter by project ID
 * @returns List of checkpoints
 */
export async function listCheckpoints(
  projectId?: string,
): Promise<CheckpointsListResponse> {
  const params = new URLSearchParams()
  if (projectId) params.set('project_id', projectId)

  const url = `/api/checkpoints${params.toString() ? `?${params}` : ''}`
  const response = await fetch(url)

  if (!response.ok) {
    throw new Error(`Failed to fetch checkpoints: ${response.statusText}`)
  }

  return response.json()
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
  const params = new URLSearchParams()
  if (projectId) params.set('project_id', projectId)

  const url = `/api/checkpoints/${taskId}${params.toString() ? `?${params}` : ''}`
  const response = await fetch(url)

  if (response.status === 404) {
    return null
  }

  if (!response.ok) {
    throw new Error(`Failed to fetch checkpoint: ${response.statusText}`)
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
    // 200 with null body is valid (no active checkpoint)
    const text = await response.text()
    if (!text || text === 'null') {
      return null
    }
    throw new Error(`Failed to fetch active checkpoint: ${response.statusText}`)
  }

  const text = await response.text()
  if (!text || text === 'null') {
    return null
  }

  return JSON.parse(text)
}
