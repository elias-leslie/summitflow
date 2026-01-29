/**
 * Tasks Table Component - Displays tasks in a table format
 */

import { Loader2 } from 'lucide-react'
import type { Task, TaskStatus } from '@/lib/api'
import { TaskRow } from './TaskRow'

interface TasksTableProps {
  tasks: Task[]
  isLoading: boolean
  expandedId: string | null
  onToggleExpand: (taskId: string) => void
  onStatusChange: (taskId: string, status: TaskStatus) => void
  isUpdating: boolean
  projectId: string
}

export function TasksTable({
  tasks,
  isLoading,
  expandedId,
  onToggleExpand,
  onStatusChange,
  isUpdating,
  projectId,
}: TasksTableProps) {
  if (isLoading) {
    return (
      <div className="p-8 flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-slate-400" />
      </div>
    )
  }

  if (tasks.length === 0) {
    return <div className="p-8 text-center text-slate-500">No tasks found</div>
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="text-xs text-slate-500 border-b border-slate-700">
            <th className="w-8 px-2 py-2"></th>
            <th className="w-12 px-2 py-2 text-left">Pri</th>
            <th className="w-10 px-2 py-2"></th>
            <th className="w-28 px-2 py-2 text-left">ID</th>
            <th className="px-2 py-2 text-left">Title</th>
            <th className="w-28 px-2 py-2 text-left">Status</th>
            <th className="w-24 px-2 py-2 text-left">Created</th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <TaskRow
              key={task.id}
              task={task}
              isExpanded={expandedId === task.id}
              onToggle={() => onToggleExpand(task.id)}
              onStatusChange={(status) => onStatusChange(task.id, status)}
              isUpdating={isUpdating}
              projectId={projectId}
            />
          ))}
        </tbody>
      </table>
    </div>
  )
}
