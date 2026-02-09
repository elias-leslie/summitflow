'use client'

import { useCallback, useState } from 'react'
import {
  type Subtask,
  type Task,
  type TaskStatus,
  updateSubtask,
  updateTask,
  updateTaskStatus,
} from '@/lib/api/tasks'

interface UseTaskActionsOptions {
  task: Task | null
  projectId: string
  onTaskUpdate?: (task: Task) => void
  setTask: (task: Task) => void
  setSubtasks: React.Dispatch<React.SetStateAction<Subtask[]>>
}

interface UseTaskActionsReturn {
  isTogglingAutonomous: boolean
  handleStatusChange: (status: TaskStatus) => Promise<void>
  handleSubtaskToggle: (subtaskId: string, passes: boolean) => Promise<void>
  handleObjectiveEdit: (objective: string) => Promise<void>
  handleToggleAutonomous: () => Promise<void>
  handleAgentOverrideChange: (agentSlug: string | null) => Promise<void>
}

export function useTaskActions({
  task,
  projectId,
  onTaskUpdate,
  setTask,
  setSubtasks,
}: UseTaskActionsOptions): UseTaskActionsReturn {
  const [isTogglingAutonomous, setIsTogglingAutonomous] = useState(false)

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
    [task, projectId, onTaskUpdate, setTask],
  )

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
    [task, projectId, setSubtasks],
  )

  const handleObjectiveEdit = useCallback(
    async (newObjective: string) => {
      if (!task) return
      onTaskUpdate?.({ ...task, objective: newObjective })
    },
    [task, onTaskUpdate],
  )

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
  }, [task, projectId, onTaskUpdate, setTask])

  const handleAgentOverrideChange = useCallback(
    async (agentSlug: string | null) => {
      if (!task) return
      try {
        const updated = await updateTask(projectId, task.id, {
          agent_override: agentSlug,
        })
        setTask(updated)
        onTaskUpdate?.(updated)
      } catch (err) {
        console.error('Failed to update agent override:', err)
      }
    },
    [task, projectId, onTaskUpdate, setTask],
  )

  return {
    isTogglingAutonomous,
    handleStatusChange,
    handleSubtaskToggle,
    handleObjectiveEdit,
    handleToggleAutonomous,
    handleAgentOverrideChange,
  }
}
