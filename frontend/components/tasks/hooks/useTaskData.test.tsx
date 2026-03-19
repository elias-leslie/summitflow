import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Task } from '@/lib/api/tasks'
import { useTaskData } from './useTaskData'

const taskApiMocks = vi.hoisted(() => ({
  fetchTask: vi.fn(),
  getSubtasksWithSteps: vi.fn(),
}))

vi.mock('@/lib/api/tasks', () => ({
  fetchTask: taskApiMocks.fetchTask,
  getSubtasksWithSteps: taskApiMocks.getSubtasksWithSteps,
}))

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
    updated_at: overrides.updated_at ?? null,
    started_at: overrides.started_at ?? null,
    completed_at: overrides.completed_at ?? null,
    priority: overrides.priority ?? 50,
    labels: overrides.labels ?? [],
    task_type: overrides.task_type ?? 'task',
    parent_task_id: overrides.parent_task_id ?? null,
  }
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void

  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })

  return { promise, resolve, reject }
}

describe('useTaskData', () => {
  beforeEach(() => {
    taskApiMocks.fetchTask.mockReset()
    taskApiMocks.getSubtasksWithSteps.mockReset()
    taskApiMocks.getSubtasksWithSteps.mockResolvedValue({ subtasks: [] })
  })

  it('clears stale task details while loading a different task', async () => {
    const firstTask = makeTask({ id: 'task-1', title: 'First task' })
    const secondTask = makeTask({ id: 'task-2', title: 'Second task' })
    const secondTaskRequest = deferred<Task>()

    taskApiMocks.fetchTask.mockReturnValue(secondTaskRequest.promise)

    const { result, rerender } = renderHook(
      ({ taskId, initialTask }) =>
        useTaskData({
          taskId,
          projectId: 'summitflow',
          open: true,
          initialTask,
        }),
      {
        initialProps: {
          taskId: firstTask.id,
          initialTask: firstTask as Task | null,
        },
      },
    )

    expect(result.current.task?.id).toBe(firstTask.id)

    rerender({
      taskId: secondTask.id,
      initialTask: null,
    })

    await waitFor(() => {
      expect(result.current.task).toBeNull()
      expect(result.current.subtasks).toEqual([])
      expect(result.current.isLoading).toBe(true)
    })

    secondTaskRequest.resolve(secondTask)

    await waitFor(() => {
      expect(result.current.task?.id).toBe(secondTask.id)
      expect(result.current.isLoading).toBe(false)
    })
  })

  it('surfaces subtask fetch failures separately from task load failures', async () => {
    const task = makeTask()

    taskApiMocks.fetchTask.mockResolvedValue(task)
    taskApiMocks.getSubtasksWithSteps.mockRejectedValue(
      new Error('Subtasks unavailable'),
    )

    const { result } = renderHook(() =>
      useTaskData({
        taskId: task.id,
        projectId: 'summitflow',
        open: true,
        initialTask: null,
      }),
    )

    await waitFor(() => {
      expect(result.current.task?.id).toBe(task.id)
      expect(result.current.subtasksError).toBe('Subtasks unavailable')
      expect(result.current.subtasks).toEqual([])
    })
  })
})
