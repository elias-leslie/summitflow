'use client'

import { useCallback, useState } from 'react'
import {
  executeTask,
  fetchTask,
  type Task,
  updateTaskStatus,
} from '@/lib/api/tasks'

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
    } catch (err) {
      console.error('Failed to start execution:', err)
      setExecutionError(
        err instanceof Error ? err.message : 'Failed to start execution',
      )
    } finally {
      setIsExecuting(false)
    }
  }, [task, projectId, onTaskUpdate, setTask])

  const handleStopExecution = useCallback(async () => {
    if (!task) return
    setIsStopping(true)
    try {
      const updated = await updateTaskStatus(projectId, task.id, 'paused')
      setTask(updated)
      onTaskUpdate?.(updated)
    } catch (err) {
      console.error('Failed to stop execution:', err)
    } finally {
      setIsStopping(false)
    }
  }, [task, projectId, onTaskUpdate, setTask])

  return {
    isExecuting,
    isStopping,
    executionError,
    handleStartExecution,
    handleStopExecution,
  }
}
