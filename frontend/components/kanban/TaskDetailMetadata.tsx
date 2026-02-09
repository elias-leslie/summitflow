'use client'

import type { Task } from '@/lib/api'

interface TaskDetailMetadataProps {
  task: Task
}

export function TaskDetailMetadata({ task }: TaskDetailMetadataProps) {
  return (
    <div className="text-xs text-slate-500 space-y-1 pt-4 border-t border-slate-800">
      <p>
        Status: <span className="text-slate-300">{task.status}</span>
      </p>
      {task.created_at && (
        <p>Created: {new Date(task.created_at).toLocaleDateString()}</p>
      )}
      {task.started_at && (
        <p>Started: {new Date(task.started_at).toLocaleDateString()}</p>
      )}
      {task.completed_at && (
        <p>Completed: {new Date(task.completed_at).toLocaleDateString()}</p>
      )}
    </div>
  )
}
