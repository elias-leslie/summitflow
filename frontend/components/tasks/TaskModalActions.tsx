'use client'

import { PanelsTopLeft } from 'lucide-react'
import type { Task, TaskStatus } from '@/lib/api/tasks'
import { AgentSelector } from './AgentSelector'
import { AutonomousToggle } from './AutonomousToggle'
import { EditDeleteActions } from './EditDeleteActions'
import { StatusActionButtons } from './StatusActionButtons'

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
  const openWorkChat = () => {
    const existingSessionId = task.agent_hub_session_ids?.at(-1)
    const params = new URLSearchParams({
      project_id: task.project_id,
      task_id: task.id,
      task_title: task.title,
    })
    if (task.description) params.set('task_summary', task.description)
    if (existingSessionId) params.set('session_id', existingSessionId)
    window.open(`/work-chats?${params.toString()}`, '_blank')
  }

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <button
        type="button"
        onClick={openWorkChat}
        className="inline-flex items-center gap-1.5 rounded-md border border-phosphor-500/30 bg-phosphor-500/10 px-3 py-1.5 text-xs font-medium text-phosphor-300 transition-colors hover:bg-phosphor-500/20"
      >
        <PanelsTopLeft className="h-3.5 w-3.5" />
        Work Chat
      </button>
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
