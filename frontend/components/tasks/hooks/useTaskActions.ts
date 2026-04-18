'use client'

import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import {
  type Subtask,
  type Task,
  type TaskStatus,
  updateSubtask,
  updateTask,
  updateTaskStatus,
} from '@/lib/api/tasks'
import { formatTaskStatus, useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

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
  const { syncUpdatedTask } = useTaskMutationSync(projectId)
  const [isTogglingAutonomous, setIsTogglingAutonomous] = useState(false)

  const handleStatusChange = useCallback(
    async (newStatus: TaskStatus) => {
      if (!task) return
      try {
        const updated = await updateTaskStatus(projectId, task.id, newStatus)
        setTask(updated)
        onTaskUpdate?.(updated)
        syncUpdatedTask(updated)
        toast.success(`Status updated to ${formatTaskStatus(newStatus)}`)
      } catch (err) {
        toast.error(getErrorMessage(err, 'Failed to update task status'))
      }
    },
    [task, onTaskUpdate, projectId, setTask, syncUpdatedTask],
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
        throw new Error(getErrorMessage(err, 'Failed to update subtask'))
      }
    },
    [task, projectId, setSubtasks],
  )

  const handleObjectiveEdit = useCallback(async (_newObjective: string) => {
    // objective field removed from Task type — no-op
  }, [])

  const handleToggleAutonomous = useCallback(async () => {
    if (!task) return
    setIsTogglingAutonomous(true)
    try {
      const updated = await updateTask(projectId, task.id, {
        autonomous: !task.autonomous,
      })
      setTask(updated)
      onTaskUpdate?.(updated)
      syncUpdatedTask(updated)
      toast.success(
        updated.autonomous
          ? 'Autonomous execution enabled'
          : 'Autonomous execution disabled',
      )
    } catch (err) {
      toast.error(getErrorMessage(err, 'Failed to update autonomous mode'))
    } finally {
      setIsTogglingAutonomous(false)
    }
  }, [task, onTaskUpdate, projectId, setTask, syncUpdatedTask])

  const handleAgentOverrideChange = useCallback(
    async (agentSlug: string | null) => {
      if (!task) return
      try {
        const updated = await updateTask(projectId, task.id, {
          agent_override: agentSlug,
        })
        setTask(updated)
        onTaskUpdate?.(updated)
        syncUpdatedTask(updated)
        toast.success(
          agentSlug ? 'Agent override updated' : 'Agent override cleared',
        )
      } catch (err) {
        toast.error(getErrorMessage(err, 'Failed to update agent override'))
      }
    },
    [task, onTaskUpdate, projectId, setTask, syncUpdatedTask],
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
