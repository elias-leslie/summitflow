import type { QueryClient } from '@tanstack/react-query'
import type { Task, TaskListResponse, TaskStatus } from '@/lib/api/tasks'

const BLOCKED_TASK_STATUSES: TaskStatus[] = ['failed']

export const taskQueryKeys = {
  root: (projectId: string) => ['tasks', projectId] as const,
  all: (projectId: string) => ['tasks', projectId, 'all'] as const,
  blocked: (projectId: string) => ['tasks', projectId, 'blocked'] as const,
  kanban: (projectId: string) => ['tasks', projectId, 'kanban'] as const,
}

function isBlockedTask(task: Task): boolean {
  return BLOCKED_TASK_STATUSES.includes(task.status)
}

export function upsertTaskInList(
  response: TaskListResponse | undefined,
  task: Task,
): TaskListResponse | undefined {
  if (!response) return response

  const existingIndex = response.tasks.findIndex((candidate) => candidate.id === task.id)
  if (existingIndex === -1) {
    return {
      ...response,
      tasks: [task, ...response.tasks],
      total: response.total + 1,
    }
  }

  return {
    ...response,
    tasks: response.tasks.map((candidate) =>
      candidate.id === task.id ? task : candidate,
    ),
  }
}

export function removeTaskFromList(
  response: TaskListResponse | undefined,
  taskId: string,
): TaskListResponse | undefined {
  if (!response) return response

  const nextTasks = response.tasks.filter((task) => task.id !== taskId)
  if (nextTasks.length === response.tasks.length) {
    return response
  }

  return {
    ...response,
    tasks: nextTasks,
    total: Math.max(0, response.total - 1),
  }
}

export function syncTaskInTaskLists(
  queryClient: QueryClient,
  projectId: string,
  task: Task,
): void {
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.all(projectId),
    (current) => upsertTaskInList(current, task),
  )
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.kanban(projectId),
    (current) => upsertTaskInList(current, task),
  )
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.blocked(projectId),
    (current) =>
      isBlockedTask(task)
        ? upsertTaskInList(current, task)
        : removeTaskFromList(current, task.id),
  )
}

export function removeTaskFromTaskLists(
  queryClient: QueryClient,
  projectId: string,
  taskId: string,
): void {
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.all(projectId),
    (current) => removeTaskFromList(current, taskId),
  )
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.kanban(projectId),
    (current) => removeTaskFromList(current, taskId),
  )
  queryClient.setQueryData<TaskListResponse | undefined>(
    taskQueryKeys.blocked(projectId),
    (current) => removeTaskFromList(current, taskId),
  )
}

export function invalidateTaskQueries(
  queryClient: QueryClient,
  projectId: string,
): Promise<void> {
  return queryClient.invalidateQueries({ queryKey: taskQueryKeys.root(projectId) })
}
