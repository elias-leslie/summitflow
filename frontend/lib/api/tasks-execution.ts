/**
 * Tasks API - Autonomous Execution & Batch Operations
 */

import { fetchWithErrorHandling, getApiBase } from './utils'
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
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/execute`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options || {}),
      errorMessage: 'Failed to start task execution',
    },
  )
}

// ============================================================================
// Batch Operations
// ============================================================================

export async function batchCreateTasks(
  projectId: string,
  items: BatchTaskCreateItem[],
): Promise<BatchTaskResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/batch`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ items }),
    errorMessage: 'Failed to batch create tasks',
  })
}
