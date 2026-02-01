'use client'

import { ExecutionBadges } from '@/components/tasks/ExecutionBadges'
import { Input } from '@/components/ui/input'
import type { Task } from '@/lib/api/tasks'
import { getPriorityColors, getTaskTypeConfig } from '@/lib/task-config'

interface TaskModalHeaderProps {
  task: Task
  isEditing: boolean
  editTitle: string
  onEditTitleChange: (title: string) => void
}

export function TaskModalHeader({
  task,
  isEditing,
  editTitle,
  onEditTitleChange,
}: TaskModalHeaderProps) {
  const colors = getPriorityColors(task.priority)
  const typeConfig = getTaskTypeConfig(task.task_type)

  return (
    <div className="border-b border-slate-700 px-6 py-4">
      <div className="flex items-center gap-2 mb-2 flex-wrap">
        <span className="mono text-sm text-slate-500">{task.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${colors.bg} ${colors.text} ${colors.border}`}
        >
          P{task.priority}
        </span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border flex items-center gap-1 ${typeConfig.className}`}
        >
          {typeConfig.icon}
          {typeConfig.label}
        </span>
        <ExecutionBadges task={task} />
      </div>
      {isEditing ? (
        <Input
          value={editTitle}
          onChange={(e) => onEditTitleChange(e.target.value)}
          className="text-lg font-semibold"
          autoFocus
        />
      ) : (
        <h2 className="display text-lg font-semibold text-white">
          {task.title}
        </h2>
      )}
    </div>
  )
}
