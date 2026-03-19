'use client'

import { TaskBadges } from '@/components/shared/TaskBadges'
import { ExecutionBadges } from '@/components/tasks/ExecutionBadges'
import { TaskModalActions } from '@/components/tasks/TaskModalActions'
import { Input } from '@/components/ui/input'
import type { Task, TaskStatus } from '@/lib/api/tasks'

interface TaskModalHeaderProps {
  task: Task
  isEditing: boolean
  editTitle: string
  onEditTitleChange: (title: string) => void
  // Action props — integrated into header
  isExecuting: boolean
  isStopping: boolean
  isTogglingAutonomous: boolean
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => Promise<void>
  onToggleAutonomous: () => void
  onAgentOverrideChange: (agentId: string | null) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onDelete: () => void
}

export function TaskModalHeader({
  task,
  isEditing,
  editTitle,
  onEditTitleChange,
  isExecuting,
  isStopping,
  isTogglingAutonomous,
  onStartExecution,
  onStopExecution,
  onStatusChange,
  onToggleAutonomous,
  onAgentOverrideChange,
  onEditStart,
  onEditCancel,
  onEditSave,
  onDelete,
}: TaskModalHeaderProps) {
  return (
    <div className="border-b border-slate-700/60 px-6 py-4 space-y-3">
      {/* Row 1: badges */}
      <TaskBadges task={task}>
        <ExecutionBadges task={task} />
      </TaskBadges>

      {/* Row 2: title */}
      {isEditing ? (
        <Input
          value={editTitle}
          onChange={(e) => onEditTitleChange(e.target.value)}
          className="text-lg font-semibold"
          autoFocus
        />
      ) : (
        <h2 className="display text-lg font-semibold text-white leading-tight">
          {task.title}
        </h2>
      )}

      {/* Row 3: action bar — contextual to status */}
      <TaskModalActions
        task={task}
        isExecuting={isExecuting}
        isStopping={isStopping}
        isTogglingAutonomous={isTogglingAutonomous}
        isEditing={isEditing}
        onStartExecution={onStartExecution}
        onStopExecution={onStopExecution}
        onStatusChange={onStatusChange}
        onToggleAutonomous={onToggleAutonomous}
        onAgentOverrideChange={onAgentOverrideChange}
        onEditStart={onEditStart}
        onEditCancel={onEditCancel}
        onEditSave={onEditSave}
        onDelete={onDelete}
      />
    </div>
  )
}
