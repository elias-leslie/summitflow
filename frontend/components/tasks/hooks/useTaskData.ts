'use client'

import { useEffect, useState } from 'react'
import {
  fetchTask,
  getSubtasksWithSteps,
  type Subtask,
  type Task,
} from '@/lib/api/tasks'
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

  // Fetch task when modal opens
  useEffect(() => {
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
      return
    }

    setTask(null)
    setIsLoading(true)
    setError(null)
    fetchTask(projectId, taskId)
      .then((data) => setTask(data))
      .catch((err) => {
        setError(getErrorMessage(err, 'Failed to load task details'))
      })
      .finally(() => setIsLoading(false))
  }, [open, taskId, projectId, initialTask])

  // Fetch subtasks when task is loaded
  useEffect(() => {
    if (open && task) {
      setIsLoadingSubtasks(true)
      setSubtasksError(null)
      getSubtasksWithSteps(projectId, task.id)
        .then((response) => setSubtasks(response.subtasks))
        .catch((err) => {
          setSubtasks([])
          setSubtasksError(getErrorMessage(err, 'Failed to load subtasks'))
        })
        .finally(() => setIsLoadingSubtasks(false))
    }
  }, [open, task, projectId])

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
