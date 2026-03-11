'use client'

import { useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import {
  executeTask,
  fetchTask,
  type Task,
  updateTaskStatus,
} from '@/lib/api/tasks'
import {
  invalidateTaskQueries,
  syncTaskInTaskLists,
} from '@/lib/task-cache'

interface UseTaskExecutionOptions {
  task: Task | null
  projectId: string
  onTaskUpdate?: (task: Task) => void
  setTask: (task: Task) => void
}

interface UseTaskExecutionReturn {
  isExecuting: boolean
  isStopping: boolean
  executionError: string | null
  handleStartExecution: () => Promise<void>
  handleStopExecution: () => Promise<void>
}

export function useTaskExecution({
  task,
  projectId,
  onTaskUpdate,
  setTask,
}: UseTaskExecutionOptions): UseTaskExecutionReturn {
  const queryClient = useQueryClient()
  const [isExecuting, setIsExecuting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [executionError, setExecutionError] = useState<string | null>(null)

  const handleStartExecution = useCallback(async () => {
    if (!task) return
    setIsExecuting(true)
    setExecutionError(null)
    try {
      await executeTask(projectId, task.id)
      const updated = await fetchTask(projectId, task.id)
      setTask(updated)
      onTaskUpdate?.(updated)
      syncTaskInTaskLists(queryClient, projectId, updated)
      void invalidateTaskQueries(queryClient, projectId)
      toast.success('Task queued for execution')
    } catch (err) {
      console.error('Failed to start execution:', err)
      setExecutionError(
        err instanceof Error ? err.message : 'Failed to start execution',
      )
      toast.error('Failed to start execution')
    } finally {
      setIsExecuting(false)
    }
  }, [task, projectId, onTaskUpdate, queryClient, setTask])

  const handleStopExecution = useCallback(async () => {
    if (!task) return
    setIsStopping(true)
    try {
      const updated = await updateTaskStatus(projectId, task.id, 'paused')
      setTask(updated)
      onTaskUpdate?.(updated)
      syncTaskInTaskLists(queryClient, projectId, updated)
      void invalidateTaskQueries(queryClient, projectId)
      toast.success('Task paused')
    } catch (err) {
      console.error('Failed to stop execution:', err)
      toast.error('Failed to pause task')
    } finally {
      setIsStopping(false)
    }
  }, [task, projectId, onTaskUpdate, queryClient, setTask])

  return {
    isExecuting,
    isStopping,
    executionError,
    handleStartExecution,
    handleStopExecution,
  }
}
