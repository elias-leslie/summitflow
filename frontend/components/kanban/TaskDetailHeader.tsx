'use client'

import { Edit2, Save, X } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import {
  SheetClose,
  SheetHeader,
  SheetTitle,
} from '@/components/ui/sheet'
import type { Task } from '@/lib/api'
import { getPriorityColors, getTaskTypeConfig } from '@/lib/task-config'

interface TaskDetailHeaderProps {
  task: Task
  isEditing: boolean
  editTitle: string
  onEditTitleChange: (title: string) => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
  onClose: () => void
}

export function TaskDetailHeader({
  task,
  isEditing,
  editTitle,
  onEditTitleChange,
  onEditStart,
  onEditCancel,
  onEditSave,
  onClose,
}: TaskDetailHeaderProps) {
  const typeConfig = getTaskTypeConfig(task.task_type)
  const colors = getPriorityColors(task.priority)

  return (
    <SheetHeader className="relative">
      <SheetClose onClose={onClose} />
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
      </div>
      <div className="flex items-center gap-2">
        {isEditing ? (
          <>
            <Input
              value={editTitle}
              onChange={(e) => onEditTitleChange(e.target.value)}
              className="text-lg font-semibold flex-1"
              autoFocus
            />
            <Button variant="outline" size="sm" onClick={onEditCancel}>
              <X className="h-4 w-4" />
            </Button>
            <Button variant="primary" size="sm" onClick={onEditSave}>
              <Save className="h-4 w-4" />
            </Button>
          </>
        ) : (
          <>
            <SheetTitle className="flex-1">{task.title}</SheetTitle>
            <Button variant="outline" size="sm" onClick={onEditStart}>
              <Edit2 className="h-4 w-4" />
            </Button>
          </>
        )}
      </div>
    </SheetHeader>
  )
}
