'use client'

import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import {
  executeTask,
  fetchTask,
  type Task,
  updateTaskStatus,
} from '@/lib/api/tasks'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

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
  const { syncUpdatedTask } = useTaskMutationSync(projectId)
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
      syncUpdatedTask(updated)
      toast.success('Task queued for execution')
    } catch (err) {
      const message = getErrorMessage(err, 'Failed to start execution')
      setExecutionError(message)
      toast.error(message)
    } finally {
      setIsExecuting(false)
    }
  }, [onTaskUpdate, projectId, setTask, syncUpdatedTask, task])

  const handleStopExecution = useCallback(async () => {
    if (!task) return
    setIsStopping(true)
    try {
      const updated = await updateTaskStatus(projectId, task.id, 'pending')
      setTask(updated)
      onTaskUpdate?.(updated)
      syncUpdatedTask(updated)
      toast.success('Task paused')
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to pause task'))
    } finally {
      setIsStopping(false)
    }
  }, [onTaskUpdate, projectId, setTask, syncUpdatedTask, task])

  return {
    isExecuting,
    isStopping,
    executionError,
    handleStartExecution,
    handleStopExecution,
  }
}
