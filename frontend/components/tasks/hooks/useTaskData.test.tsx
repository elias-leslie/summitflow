import { renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Task } from '@/lib/api/tasks'
import { makeTask } from '@/tests/factories'
import { useTaskData } from './useTaskData'

const taskApiMocks = vi.hoisted(() => ({
  fetchTask: vi.fn(),
  getSubtasksWithSteps: vi.fn(),
}))

vi.mock('@/lib/api/tasks', () => ({
  fetchTask: taskApiMocks.fetchTask,
  getSubtasksWithSteps: taskApiMocks.getSubtasksWithSteps,
}))

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
