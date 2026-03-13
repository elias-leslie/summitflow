'use client'

import { CheckCircle2, Loader2 } from 'lucide-react'
import type { Task } from '@/lib/api'
import { SortIndicator } from './SortIndicator'
import { TaskListRow } from './TaskListRow'

type SortField = 'priority' | 'type' | 'title' | 'status' | 'created_at'
type SortDirection = 'asc' | 'desc'

interface TasksTabTableProps {
  tasks: Task[]
  isLoading: boolean
  sortField: SortField
  sortDirection: SortDirection
  onSort: (field: SortField) => void
  selectedTaskIds: Set<string>
  onToggleSelect: (taskId: string) => void
  onToggleSelectAll: (tasks: Task[]) => void
  onTaskClick: (task: Task) => void
  onDeleteClick: (taskId: string) => void
}

export function TasksTabTable({
  tasks,
  isLoading,
  sortField,
  sortDirection,
  onSort,
  selectedTaskIds,
  onToggleSelect,
  onToggleSelectAll,
  onTaskClick,
  onDeleteClick,
}: TasksTabTableProps) {
  const handleSortKeyDown = (field: SortField) => (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      onSort(field)
    }
  }

  if (isLoading) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-slate-500" />
        </div>
      </div>
    )
  }

  if (tasks.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
        <div className="flex flex-col items-center justify-center py-12 text-slate-500">
          <CheckCircle2 className="h-8 w-8 mb-2" />
          <span className="text-sm">No tasks found</span>
          <span className="text-xs text-slate-600">
            Try adjusting your filters
          </span>
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden">
      <table className="w-full">
        <thead>
          <tr className="border-b border-slate-700 bg-slate-800/50">
            <th className="w-8 px-2 py-2">
              <input
                type="checkbox"
                checked={tasks.length > 0 && selectedTaskIds.size === tasks.length}
                onChange={() => onToggleSelectAll(tasks)}
                className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
              />
            </th>
            <th className="w-8 px-2 py-2"></th>
            <th
              role="button"
              tabIndex={0}
              className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16 cursor-pointer hover:text-slate-200 select-none"
              onClick={() => onSort('priority')}
              onKeyDown={handleSortKeyDown('priority')}
            >
              Pri
              <SortIndicator
                field="priority"
                currentField={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              role="button"
              tabIndex={0}
              className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-20 cursor-pointer hover:text-slate-200 select-none"
              onClick={() => onSort('type')}
              onKeyDown={handleSortKeyDown('type')}
            >
              Type
              <SortIndicator
                field="type"
                currentField={sortField}
                direction={sortDirection}
              />
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-28">
              ID
            </th>
            <th
              role="button"
              tabIndex={0}
              className="px-3 py-2 text-left text-xs font-medium text-slate-400 cursor-pointer hover:text-slate-200 select-none"
              onClick={() => onSort('title')}
              onKeyDown={handleSortKeyDown('title')}
            >
              Title
              <SortIndicator
                field="title"
                currentField={sortField}
                direction={sortDirection}
              />
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-36">
              Progress
            </th>
            <th
              role="button"
              tabIndex={0}
              className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24 cursor-pointer hover:text-slate-200 select-none"
              onClick={() => onSort('status')}
              onKeyDown={handleSortKeyDown('status')}
            >
              Status
              <SortIndicator
                field="status"
                currentField={sortField}
                direction={sortDirection}
              />
            </th>
            <th
              role="button"
              tabIndex={0}
              className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-24 cursor-pointer hover:text-slate-200 select-none"
              onClick={() => onSort('created_at')}
              onKeyDown={handleSortKeyDown('created_at')}
            >
              Created
              <SortIndicator
                field="created_at"
                currentField={sortField}
                direction={sortDirection}
              />
            </th>
            <th className="px-3 py-2 text-left text-xs font-medium text-slate-400 w-16">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          {tasks.map((task) => (
            <TaskListRow
              key={task.id}
              task={task}
              isExpanded={false}
              onToggle={() => onTaskClick(task)}
              onDelete={onDeleteClick}
              isSelected={selectedTaskIds.has(task.id)}
              onToggleSelect={onToggleSelect}
              subtasks={[]}
            />
          ))}
        </tbody>
      </table>

      <div className="px-4 py-2 border-t border-slate-700 bg-slate-800/30">
        <span className="text-xs text-slate-500">
          {tasks.length} task{tasks.length !== 1 ? 's' : ''}
        </span>
      </div>
    </div>
  )
}
