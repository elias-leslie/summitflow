import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it } from 'vitest'
import type { Task } from '@/lib/api/tasks'
import {
  invalidateTaskQueries,
  removeTaskFromList,
  removeTaskFromTaskLists,
  syncTaskInTaskLists,
  taskQueryKeys,
  upsertTaskInList,
} from './task-cache'

function makeTask(overrides: Partial<Task> = {}): Task {
  return {
    id: overrides.id ?? 'task-1',
    project_id: overrides.project_id ?? 'summitflow',
    capability_id: overrides.capability_id ?? null,
    title: overrides.title ?? 'Test task',
    description: overrides.description ?? null,
    status: overrides.status ?? 'pending',
    plan_content: overrides.plan_content ?? null,
    progress_log: overrides.progress_log ?? null,
    error_message: overrides.error_message ?? null,
    branch_name: overrides.branch_name ?? null,
    commits: overrides.commits ?? [],
    total_sessions: overrides.total_sessions ?? 0,
    total_tokens_used: overrides.total_tokens_used ?? 0,
    created_at: overrides.created_at ?? null,
    started_at: overrides.started_at ?? null,
    completed_at: overrides.completed_at ?? null,
    priority: overrides.priority ?? 50,
    labels: overrides.labels ?? [],
    task_type: overrides.task_type ?? 'task',
    parent_task_id: overrides.parent_task_id ?? null,
    ...overrides,
  }
}

describe('task-cache', () => {
  const queryClient = new QueryClient()

  afterEach(() => {
    queryClient.clear()
  })

  it('upserts new tasks and increments totals', () => {
    const response = {
      tasks: [makeTask({ id: 'task-1' })],
      total: 1,
    }

    const updated = upsertTaskInList(response, makeTask({ id: 'task-2' }))

    expect(updated?.tasks.map((task) => task.id)).toEqual(['task-2', 'task-1'])
    expect(updated?.total).toBe(2)
  })

  it('removes deleted tasks and decrements totals', () => {
    const response = {
      tasks: [makeTask({ id: 'task-1' }), makeTask({ id: 'task-2' })],
      total: 2,
    }

    const updated = removeTaskFromList(response, 'task-1')

    expect(updated?.tasks.map((task) => task.id)).toEqual(['task-2'])
    expect(updated?.total).toBe(1)
  })

  it('syncs blocked and non-blocked task status across cached task lists', () => {
    const projectId = 'summitflow'
    const blockedTask = makeTask({ id: 'task-1', status: 'blocked' })
    const queuedTask = makeTask({ id: 'task-1', status: 'queue' })

    queryClient.setQueryData(taskQueryKeys.all(projectId), {
      tasks: [blockedTask],
      total: 1,
    })
    queryClient.setQueryData(taskQueryKeys.kanban(projectId), {
      tasks: [blockedTask],
      total: 1,
    })
    queryClient.setQueryData(taskQueryKeys.blocked(projectId), {
      tasks: [blockedTask],
      total: 1,
    })

    syncTaskInTaskLists(queryClient, projectId, queuedTask)

    expect(
      queryClient.getQueryData<{ tasks: Task[]; total: number }>(
        taskQueryKeys.all(projectId),
      )?.tasks[0].status,
    ).toBe('queue')
    expect(
      queryClient.getQueryData<{ tasks: Task[]; total: number }>(
        taskQueryKeys.kanban(projectId),
      )?.tasks[0].status,
    ).toBe('queue')
    expect(
      queryClient.getQueryData<{ tasks: Task[]; total: number }>(
        taskQueryKeys.blocked(projectId),
      ),
    ).toEqual({
      tasks: [],
      total: 0,
    })
  })

  it('removes tasks from all cached task lists', () => {
    const projectId = 'summitflow'
    const task = makeTask({ id: 'task-1', status: 'blocked' })

    queryClient.setQueryData(taskQueryKeys.all(projectId), {
      tasks: [task],
      total: 1,
    })
    queryClient.setQueryData(taskQueryKeys.kanban(projectId), {
      tasks: [task],
      total: 1,
    })
    queryClient.setQueryData(taskQueryKeys.blocked(projectId), {
      tasks: [task],
      total: 1,
    })

    removeTaskFromTaskLists(queryClient, projectId, task.id)

    expect(queryClient.getQueryData(taskQueryKeys.all(projectId))).toEqual({
      tasks: [],
      total: 0,
    })
    expect(queryClient.getQueryData(taskQueryKeys.kanban(projectId))).toEqual({
      tasks: [],
      total: 0,
    })
    expect(queryClient.getQueryData(taskQueryKeys.blocked(projectId))).toEqual({
      tasks: [],
      total: 0,
    })
  })

  it('invalidates the project task query family', async () => {
    const projectId = 'summitflow'
    queryClient.setQueryData(taskQueryKeys.all(projectId), {
      tasks: [makeTask()],
      total: 1,
    })

    await invalidateTaskQueries(queryClient, projectId)

    expect(
      queryClient.getQueryState(taskQueryKeys.all(projectId))?.isInvalidated,
    ).toBe(true)
  })
})
