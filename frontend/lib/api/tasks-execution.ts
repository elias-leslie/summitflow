/**
 * Tasks API - Autonomous Execution & Batch Operations
 */

import { getApiBaseUrl } from '../api-config'
import { postJson } from './utils'
import type {
  ExecuteTaskOptions,
  ExecuteTaskResponse,
  BatchTaskCreateItem,
  BatchTaskResponse,
} from './tasks-types'

// ============================================================================
// Autonomous Execution
// ============================================================================

/**
 * Start autonomous orchestrator execution for a task.
 * Queues the task for execution via Hatchet workflow with streaming to WebSocket.
 */
export async function executeTask(
  projectId: string,
  taskId: string,
  options?: ExecuteTaskOptions,
): Promise<ExecuteTaskResponse> {
  return postJson(
    `${getApiBaseUrl()}/api/projects/${projectId}/tasks/${taskId}/execute`,
    options || {},
    'Failed to start task execution',
  )
}

// ============================================================================
// Batch Operations
// ============================================================================

export async function batchCreateTasks(
  projectId: string,
  items: BatchTaskCreateItem[],
): Promise<BatchTaskResponse> {
  return postJson(`/api/projects/${projectId}/tasks/batch`, { items }, 'Failed to batch create tasks')
}
