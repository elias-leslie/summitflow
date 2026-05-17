'use client'

import { useEffect, useState } from 'react'
import {
  fetchTask,
  getSubtasksWithSteps,
  type Subtask,
  type Task,
  type TaskStatus,
} from '@/lib/api/tasks'
import { POLL_FAST } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

interface UseTaskDataOptions {
  taskId: string | null
  projectId: string
  open: boolean
  initialTask?: Task | null
}

interface UseTaskDataReturn {
  task: Task | null
  setTask: (task: Task | null) => void
  subtasks: Subtask[]
  setSubtasks: React.Dispatch<React.SetStateAction<Subtask[]>>
  isLoading: boolean
  isLoadingSubtasks: boolean
  error: string | null
  subtasksError: string | null
}

const TERMINAL_TASK_STATUSES = new Set<TaskStatus>([
  'completed',
  'failed',
  'cancelled',
])

function isTerminalTaskStatus(status: TaskStatus | undefined): boolean {
  return status ? TERMINAL_TASK_STATUSES.has(status) : false
}

export function useTaskData({
  taskId,
  projectId,
  open,
  initialTask,
}: UseTaskDataOptions): UseTaskDataReturn {
  const [task, setTask] = useState<Task | null>(initialTask || null)
  const [subtasks, setSubtasks] = useState<Subtask[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [subtasksError, setSubtasksError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    if (!open || !taskId) {
      setTask(null)
      setSubtasks([])
      setIsLoading(false)
      setError(null)
      setSubtasksError(null)
      return
    }

    setSubtasks([])
    setSubtasksError(null)
    if (initialTask && initialTask.id === taskId) {
      setTask(initialTask)
      setIsLoading(false)
      setError(null)
    } else {
      setTask(null)
      setIsLoading(true)
      setError(null)
    }

    fetchTask(projectId, taskId)
      .then((data) => {
        if (!cancelled) {
          setTask(data)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setError(getErrorMessage(err, 'Failed to load task details'))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [open, taskId, projectId, initialTask?.id])

  useEffect(() => {
    if (!open || !task?.id) {
      return
    }

    let cancelled = false

    setIsLoadingSubtasks(true)
    setSubtasksError(null)
    getSubtasksWithSteps(projectId, task.id)
      .then((response) => {
        if (!cancelled) {
          setSubtasks(response.subtasks)
        }
      })
      .catch((err) => {
        if (!cancelled) {
          setSubtasks([])
          setSubtasksError(getErrorMessage(err, 'Failed to load subtasks'))
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoadingSubtasks(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [open, task?.id, projectId])

  useEffect(() => {
    if (!open || !taskId || isTerminalTaskStatus(task?.status)) {
      return
    }

    let cancelled = false

    const interval = setInterval(() => {
      fetchTask(projectId, taskId)
        .then((data) => {
          if (!cancelled) {
            setTask(data)
            setError(null)
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setError(getErrorMessage(err, 'Failed to load task details'))
          }
        })

      getSubtasksWithSteps(projectId, taskId)
        .then((response) => {
          if (!cancelled) {
            setSubtasks(response.subtasks)
            setSubtasksError(null)
          }
        })
        .catch((err) => {
          if (!cancelled) {
            setSubtasksError(getErrorMessage(err, 'Failed to load subtasks'))
          }
        })
    }, POLL_FAST)

    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [open, projectId, task?.status, taskId])

  return {
    task,
    setTask,
    subtasks,
    setSubtasks,
    isLoading,
    isLoadingSubtasks,
    error,
    subtasksError,
  }
}
