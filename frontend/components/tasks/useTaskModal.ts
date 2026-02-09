'use client'

import { useEffect } from 'react'
import type { Subtask, Task, TaskStatus } from '@/lib/api/tasks'
import { useCollapsibleSections } from '@/components/tasks/hooks/useCollapsibleSections'
import { useTaskActions } from '@/components/tasks/hooks/useTaskActions'
import { useTaskData } from '@/components/tasks/hooks/useTaskData'
import { useTaskEdit } from '@/components/tasks/hooks/useTaskEdit'
import { useTaskExecution } from '@/components/tasks/hooks/useTaskExecution'

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
  agentTimelineOpen: boolean
  setDescriptionOpen: (open: boolean) => void
  setSubtasksOpen: (open: boolean) => void
  setTimelineOpen: (open: boolean) => void
  setAgentTimelineOpen: (open: boolean) => void

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
  handleAgentOverrideChange: (agentSlug: string | null) => Promise<void>
}

export function useTaskModal({
  taskId,
  projectId,
  open,
  initialTask,
  onTaskUpdate,
}: UseTaskModalOptions): UseTaskModalReturn {
  // Data fetching and state
  const {
    task,
    setTask,
    subtasks,
    setSubtasks,
    isLoading,
    isLoadingSubtasks,
    error,
  } = useTaskData({ taskId, projectId, open, initialTask })

  // Edit functionality
  const {
    isEditing,
    editTitle,
    editDescription,
    setEditTitle,
    setEditDescription,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    resetEditState,
  } = useTaskEdit({ task, projectId, onTaskUpdate, setTask })

  // Execution functionality
  const {
    isExecuting,
    isStopping,
    executionError,
    handleStartExecution,
    handleStopExecution,
  } = useTaskExecution({ task, projectId, onTaskUpdate, setTask })

  // Task actions (status, subtasks, autonomous, agent override)
  const {
    isTogglingAutonomous,
    handleStatusChange,
    handleSubtaskToggle,
    handleObjectiveEdit,
    handleToggleAutonomous,
    handleAgentOverrideChange,
  } = useTaskActions({ task, projectId, onTaskUpdate, setTask, setSubtasks })

  // Collapsible sections
  const {
    descriptionOpen,
    subtasksOpen,
    timelineOpen,
    agentTimelineOpen,
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    setAgentTimelineOpen,
    resetCollapsibleState,
  } = useCollapsibleSections()

  // Reset state when modal closes
  useEffect(() => {
    if (!open) {
      resetEditState()
      resetCollapsibleState()
    }
  }, [open, resetEditState, resetCollapsibleState])

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
    agentTimelineOpen,
    setDescriptionOpen,
    setSubtasksOpen,
    setTimelineOpen,
    setAgentTimelineOpen,
    handleEditStart,
    handleEditCancel,
    handleEditSave,
    handleStatusChange,
    handleSubtaskToggle,
    handleStartExecution,
    handleStopExecution,
    handleObjectiveEdit,
    handleToggleAutonomous,
    handleAgentOverrideChange,
  }
}
