'use client'

import type { Task, TaskStatus } from '@/lib/api/tasks'
import { AgentSelector } from './AgentSelector'
import { EditDeleteActions } from './EditDeleteActions'
import { StatusActionButtons } from './StatusActionButtons'

interface TaskModalActionsProps {
  task: Task
  isEditing: boolean
  onStatusChange: (status: TaskStatus) => Promise<void>
  onAgentOverrideChange?: (agentSlug: string | null) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete?: () => void
}

export function TaskModalActions({
  task,
  isEditing,
  onStatusChange,
  onAgentOverrideChange,
  onEditStart,
  onEditCancel,
  onEditSave,
  onDelete,
}: TaskModalActionsProps) {
  const isRunning = task.status === 'running'
  return (
    <div className="flex items-center gap-2 flex-wrap">
      <StatusActionButtons
        status={task.status}
        onStatusChange={onStatusChange}
      />
      <AgentSelector
        autonomous={task.autonomous}
        agentOverride={task.agent_override}
        taskType={task.task_type}
        isRunning={isRunning}
        onAgentOverrideChange={onAgentOverrideChange}
      />
      <EditDeleteActions
        isEditing={isEditing}
        onEditStart={onEditStart}
        onEditCancel={onEditCancel}
        onEditSave={onEditSave}
        onDelete={onDelete}
      />
    </div>
  )
}
