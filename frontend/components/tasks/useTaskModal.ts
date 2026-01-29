'use client'

import { useCallback, useEffect, useState } from 'react'
import {
  executeTask,
  fetchTask,
  getSubtasksWithSteps,
  type Subtask,
  type Task,
  type TaskStatus,
  updateSubtask,
  updateTask,
  updateTaskStatus,
} from '@/lib/api/tasks'

interface UseTaskModalOptions {
  taskId: string | null
  projectId: string
  open: boolean
  initialTask?: Task | null
  onTaskUpdate?: (task: Task) => void
}

interface UseTaskModalReturn {
  // Task data
  task: Task | null
  subtasks: Subtask[]
  isLoading: boolean
  isLoadingSubtasks: boolean
  error: string | null

  // Edit state
  isEditing: boolean
  editTitle: string
  editDescription: string
  setEditTitle: (title: string) => void
  setEditDescription: (description: string) => void

  // Execution state
  isExecuting: boolean
  isStopping: boolean
  executionError: string | null
  isTogglingAutonomous: boolean

  // Collapsible state
  descriptionOpen: boolean
  subtasksOpen: boolean
  timelineOpen: boolean
  setDescriptionOpen: (open: boolean) => void
  setSubtasksOpen: (open: boolean) => void
  setTimelineOpen: (open: boolean) => void

  // Handlers
  handleEditStart: () => void
  handleEditCancel: () => void
  handleEditSave: () => Promise<void>
  handleStatusChange: (status: TaskStatus) => Promise<void>
  handleSubtaskToggle: (subtaskId: string, passes: boolean) => Promise<void>
  handleStartExecution: () => Promise<void>
  handleStopExecution: () => Promise<void>
  handleObjectiveEdit: (objective: string) => Promise<void>
  handleToggleAutonomous: () => Promise<void>
}

export function useTaskModal({
  taskId,
  projectId,
  open,
  initialTask,
  onTaskUpdate,
}: UseTaskModalOptions): UseTaskModalReturn {
  // Task data state
  const [task, setTask] = useState<Task | null>(initialTask || null)
  const [subtasks, setSubtasks] = useState<Subtask[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [isLoadingSubtasks, setIsLoadingSubtasks] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Edit state
  const [isEditing, setIsEditing] = useState(false)
  const [editTitle, setEditTitle] = useState('')
  const [editDescription, setEditDescription] = useState('')

  // Execution state
  const [isExecuting, setIsExecuting] = useState(false)
  const [isStopping, setIsStopping] = useState(false)
  const [executionError, setExecutionError] = useState<string | null>(null)
  const [isTogglingAutonomous, setIsTogglingAutonomous] = useState(false)

  // Collapsible section state (all collapsed by default)
  const [descriptionOpen, setDescriptionOpen] = useState(false)
  const [subtasksOpen, setSubtasksOpen] = useState(false)
  const [timelineOpen, setTimelineOpen] = useState(false)

  // Fetch task when modal opens
  useEffect(() => {
    if (open && taskId) {
      if (initialTask && initialTask.id === taskId) {
        setTask(initialTask)
        setIsLoading(false)
      } else {
        setIsLoading(true)
        setError(null)
        fetchTask(projectId, taskId)
          .then((data) => setTask(data))
          .catch((err) => {
            console.error('Failed to fetch task:', err)
            setError('Failed to load task details')
          })
          .finally(() => setIsLoading(false))
      }
    }
  }, [open, taskId, projectId, initialTask])

  // Fetch subtasks when task is loaded
  useEffect(() => {
    if (open && task) {
      setIsLoadingSubtasks(true)
      getSubtasksWithSteps(projectId, task.id)
        .then((response) => setSubtasks(response.subtasks))
        .catch((err) => {
          console.error('Failed to fetch subtasks:', err)
          setSubtasks([])
        })
        .finally(() => setIsLoadingSubtasks(false))
    }
  }, [open, task, projectId])

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      setIsEditing(false)
      setEditTitle('')
      setEditDescription('')
      setError(null)
      setDescriptionOpen(false)
      setSubtasksOpen(false)
      setTimelineOpen(false)
    }
  }, [open])

  // Edit handlers
  const handleEditStart = useCallback(() => {
    if (!task) return
    setEditTitle(task.title)
    setEditDescription(task.description || '')
    setIsEditing(true)
  }, [task])

  const handleEditCancel = useCallback(() => {
    setIsEditing(false)
    setEditTitle('')
    setEditDescription('')
  }, [])

  const handleEditSave = useCallback(async () => {
    if (!task) return
    try {
      const updated = await updateTask(projectId, task.id, {
        title: editTitle,
        description: editDescription,
      })
      setTask(updated)
      onTaskUpdate?.(updated)
      setIsEditing(false)
    } catch (err) {
      console.error('Failed to update task:', err)
    }
  }, [task, projectId, editTitle, editDescription, onTaskUpdate])

  // Status change handler
  const handleStatusChange = useCallback(
    async (newStatus: TaskStatus) => {
      if (!task) return
      try {
        const updated = await updateTaskStatus(projectId, task.id, newStatus)
        setTask(updated)
        onTaskUpdate?.(updated)
      } catch (err) {
        console.error('Failed to update status:', err)
      }
    },
    [task, projectId, onTaskUpdate],
  )

  // Subtask toggle handler
  const handleSubtaskToggle = useCallback(
    async (subtaskId: string, passes: boolean) => {
      if (!task) return
      try {
        const updated = await updateSubtask(
          projectId,
          task.id,
          subtaskId,
          passes,
        )
        setSubtasks((prev) =>
          prev.map((s) =>
            s.subtask_id === subtaskId ? { ...s, ...updated } : s,
          ),
        )
      } catch (err) {
        console.error('Failed to update subtask:', err)
        throw err
      }
    },
    [task, projectId],
  )

  // Execution handlers
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
  }, [task, projectId, onTaskUpdate])

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
  }, [task, projectId, onTaskUpdate])

  // Objective edit handler
  const handleObjectiveEdit = useCallback(
    async (newObjective: string) => {
      if (!task) return
      onTaskUpdate?.({ ...task, objective: newObjective })
    },
    [task, onTaskUpdate],
  )

  // Toggle autonomous
  const handleToggleAutonomous = useCallback(async () => {
    if (!task) return
    setIsTogglingAutonomous(true)
    try {
      const updated = await updateTask(projectId, task.id, {
        autonomous: !task.autonomous,
      })
      setTask(updated)
      onTaskUpdate?.(updated)
    } catch (err) {
      console.error('Failed to toggle autonomous:', err)
    } finally {
      setIsTogglingAutonomous(false)
    }
  }, [task, projectId, onTaskUpdate])

  return {
    task,
    subtasks,
    isLoading,
    isLoadingSubtasks,
    error,
    isEditing,
    editTitle,
    editDescription,
    setEditTitle,
    setEditDescription,
    isExecuting,
    isStopping,
    executionError,
    isTogglingAutonomous,
    descriptionOpen,
    subtasksOpen,
    timelineOpen,
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    handleStatusChange,
    handleSubtaskToggle,
    handleStartExecution,
    handleStopExecution,
    handleObjectiveEdit,
    handleToggleAutonomous,
  }
}
