/**
 * Tasks API - Core CRUD Operations
 */

import { getApiBaseUrl } from '../api-config'
import type {
  DeleteTaskResponse,
  ExecuteTaskOptions,
  Task,
  TaskListResponse,
  TaskStatus,
  TaskType,
} from './tasks-types'
import {
  buildQueryString,
  fetchWithErrorHandling,
  patchJson,
  postJson,
} from './utils'

// ============================================================================
// Create & Update
// ============================================================================

export async function createTask(
  projectId: string,
  task: {
    title: string
    description?: string
    capability_id?: number
    priority?: number
    labels?: string[]
    task_type?: TaskType
    parent_task_id?: string
    execution_mode?: 'manual' | 'autonomous' | 'manual_only'
    autonomous?: boolean
  },
): Promise<Task> {
  return postJson(
    `/api/projects/${projectId}/tasks`,
    task,
    'Failed to create task',
  )
}

export async function updateTask(
  projectId: string,
  taskId: string,
  updates: {
    title?: string
    description?: string
    priority?: number
    labels?: string[]
    task_type?: TaskType
    parent_task_id?: string
    execution_mode?: 'manual' | 'autonomous' | 'manual_only'
    autonomous?: boolean
    agent_override?: string | null
  },
): Promise<Task> {
  return patchJson(
    `/api/projects/${projectId}/tasks/${taskId}`,
    updates,
    'Failed to update task',
  )
}

// ============================================================================
// Read Operations
// ============================================================================

export async function fetchTask(
  projectId: string,
  taskId: string,
): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    errorMessage: 'Failed to fetch task',
  })
}

export async function fetchTasks(
  projectId: string,
  options: {
    status?: TaskStatus
    type?: TaskType
    priority?: number
    labels?: string
    include?: string
    limit?: number
    offset?: number
  } = {},
): Promise<TaskListResponse> {
  const query = buildQueryString(options)
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks${query}`, {
    errorMessage: 'Failed to fetch tasks',
  })
}

// ============================================================================
// Task Execution Control
// ============================================================================

/**
 * Start autonomous orchestrator execution for a task.
 * Queues the task for execution via Hatchet workflow with streaming to WebSocket.
 */
export async function executeTask(
  projectId: string,
  taskId: string,
  options?: ExecuteTaskOptions,
): Promise<Task> {
  return postJson(
    `${getApiBaseUrl()}/api/projects/${projectId}/tasks/${taskId}/execute`,
    options || {},
    'Failed to start task execution',
  )
}

export interface ExecuteTasksResult {
  queued: Task[]
  failed: Array<{ taskId: string; error: string }>
}

export async function executeTasks(
  projectId: string,
  taskIds: string[],
  options?: ExecuteTaskOptions,
): Promise<ExecuteTasksResult> {
  const result: ExecuteTasksResult = { queued: [], failed: [] }
  for (const taskId of taskIds) {
    try {
      result.queued.push(await executeTask(projectId, taskId, options))
    } catch (error) {
      result.failed.push({
        taskId,
        error: error instanceof Error ? error.message : 'Failed to queue task',
      })
    }
  }
  return result
}

export async function updateTaskStatus(
  projectId: string,
  taskId: string,
  status: TaskStatus,
  taskErrorMessage?: string,
): Promise<Task> {
  return patchJson(
    `${getApiBaseUrl()}/api/projects/${projectId}/tasks/${taskId}/status`,
    { status, error_message: taskErrorMessage },
    'Failed to update task status',
  )
}

// ============================================================================
// Delete Operations
// ============================================================================

/**
 * Delete a task (hard delete with cascading).
 */
export async function deleteTask(
  projectId: string,
  taskId: string,
): Promise<DeleteTaskResponse> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    method: 'DELETE',
    errorMessage: 'Failed to delete task',
  })
}

/**
 * Delete multiple tasks in bulk.
 */
export async function deleteTasks(
  projectId: string,
  taskIds: string[],
): Promise<DeleteTaskResponse[]> {
  return Promise.all(taskIds.map((taskId) => deleteTask(projectId, taskId)))
}
