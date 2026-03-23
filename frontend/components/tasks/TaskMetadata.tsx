'use client'

import type { Task } from '@/lib/api/tasks'
import { formatShortDate } from '@/lib/format'

interface TaskMetadataProps {
  task: Task
}

export function TaskMetadata({ task }: TaskMetadataProps) {
  return (
    <div className="text-xs text-slate-500 space-y-1 pt-4 border-t border-slate-800">
      <p>
        Status: <span className="text-slate-300">{task.status}</span>
      </p>
      {task.created_at && (
        <p>Created: {formatShortDate(task.created_at)}</p>
      )}
      {task.updated_at && (
        <p>Updated: {formatShortDate(task.updated_at)}</p>
      )}
      {task.started_at && (
        <p>Started: {formatShortDate(task.started_at)}</p>
      )}
      {task.completed_at && (
        <p>Completed: {formatShortDate(task.completed_at)}</p>
      )}
    </div>
  )
}
