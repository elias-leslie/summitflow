'use client'

import type { Task, TaskStatus } from '@/lib/api/tasks'
import { StatusActionButtons } from './StatusActionButtons'
import { AutonomousToggle } from './AutonomousToggle'
import { AgentSelector } from './AgentSelector'
import { EditDeleteActions } from './EditDeleteActions'

interface TaskModalActionsProps {
  task: Task
  isExecuting: boolean
  isStopping: boolean
  isTogglingAutonomous: boolean
  isEditing: boolean
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => Promise<void>
  onToggleAutonomous: () => void
  onAgentOverrideChange?: (agentSlug: string | null) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete?: () => void
}

export function TaskModalActions({
  task,
  isExecuting,
  isStopping,
  isTogglingAutonomous,
  isEditing,
  onStartExecution,
  onStopExecution,
  onStatusChange,
  onToggleAutonomous,
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
        isExecuting={isExecuting}
        isStopping={isStopping}
        onStartExecution={onStartExecution}
        onStopExecution={onStopExecution}
        onStatusChange={onStatusChange}
      />
      <AutonomousToggle
        autonomous={task.autonomous}
        isToggling={isTogglingAutonomous}
        isRunning={isRunning}
        onToggle={onToggleAutonomous}
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
