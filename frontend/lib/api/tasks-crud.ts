/**
 * Tasks API - Core CRUD Operations
 */

import { buildQueryString, fetchWithErrorHandling, getApiBase } from './utils'
import type {
  Task,
  TaskListResponse,
  TaskStatus,
  TaskType,
  AgentType,
  StartTaskResult,
  DeleteTaskResponse,
} from './tasks-types'

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
  },
): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(task),
    errorMessage: 'Failed to create task',
  })
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
    autonomous?: boolean
    agent_override?: string | null
  },
): Promise<Task> {
  return fetchWithErrorHandling(`/api/projects/${projectId}/tasks/${taskId}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
    errorMessage: 'Failed to update task',
  })
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

export async function fetchReadyTasks(
  projectId: string,
  limit = 50,
): Promise<TaskListResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/ready?limit=${limit}`,
    {
      errorMessage: 'Failed to fetch ready tasks',
    },
  )
}

export async function fetchBlockedTasks(
  projectId: string,
  limit = 50,
): Promise<TaskListResponse> {
  return fetchWithErrorHandling(
    `/api/projects/${projectId}/tasks/blocked?limit=${limit}`,
    {
      errorMessage: 'Failed to fetch blocked tasks',
    },
  )
}

// ============================================================================
// Task Execution Control
// ============================================================================

export async function startTask(
  projectId: string,
  taskId: string,
  options: {
    agent_type: AgentType
    model?: string
    allow_delegation?: boolean
  },
): Promise<StartTaskResult> {
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(options),
      errorMessage: 'Failed to start task',
    },
  )
}

export async function updateTaskStatus(
  projectId: string,
  taskId: string,
  status: TaskStatus,
  taskErrorMessage?: string,
): Promise<Task> {
  return fetchWithErrorHandling(
    `${getApiBase()}/api/projects/${projectId}/tasks/${taskId}/status`,
    {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status, error_message: taskErrorMessage }),
      errorMessage: 'Failed to update task status',
    },
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
