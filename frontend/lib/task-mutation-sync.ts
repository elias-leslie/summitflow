'use client'

import { useCallback } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import type { Task, TaskStatus } from '@/lib/api/tasks'
import {
  invalidateTaskQueries,
  removeTaskFromTaskLists,
  syncTaskInTaskLists,
} from './task-cache'

export function formatTaskStatus(status: TaskStatus): string {
  return status.replaceAll('_', ' ')
}

export function useTaskMutationSync(projectId: string) {
  const queryClient = useQueryClient()

  const syncUpdatedTask = useCallback(
    (task: Task) => {
      syncTaskInTaskLists(queryClient, projectId, task)
      void invalidateTaskQueries(queryClient, projectId)
    },
    [projectId, queryClient],
  )

  const syncDeletedTask = useCallback(
    (taskId: string) => {
      removeTaskFromTaskLists(queryClient, projectId, taskId)
      void invalidateTaskQueries(queryClient, projectId)
    },
    [projectId, queryClient],
  )

  const invalidateTasks = useCallback(() => {
    void invalidateTaskQueries(queryClient, projectId)
  }, [projectId, queryClient])

  return {
    syncUpdatedTask,
    syncDeletedTask,
    invalidateTasks,
  }
}
