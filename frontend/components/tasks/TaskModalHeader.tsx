'use client'

import { TaskBadges } from '@/components/shared/TaskBadges'
import { ExecutionBadges } from '@/components/tasks/ExecutionBadges'
import { Input } from '@/components/ui/input'
import type { Task } from '@/lib/api/tasks'

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
  return (
    <div className="border-b border-slate-700 px-6 py-4">
      <TaskBadges task={task}>
        <ExecutionBadges task={task} />
      </TaskBadges>
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
