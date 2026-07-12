'use client'

import { CheckCircle2 } from 'lucide-react'
import type { Task } from '@/lib/api'
import { SortIndicator } from './SortIndicator'
import { TaskListRow } from './TaskListRow'
import { TaskQueryState } from './TaskQueryState'

type SortField = 'priority' | 'type' | 'title' | 'status' | 'updated_at'
type SortDirection = 'asc' | 'desc'

interface TasksTabTableProps {
  tasks: Task[]
  error: unknown
  isLoading: boolean
  onRetry: () => void
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
  error,
  isLoading,
  onRetry,
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

  return (
    <TaskQueryState
      error={error}
      isLoading={isLoading}
      loadingLabel="Loading tasks..."
      onRetry={onRetry}
    >
      {tasks.length === 0 ? (
        <div className="overflow-hidden rounded-lg border border-slate-700 bg-slate-900/50">
          <div className="flex flex-col items-center justify-center py-12 text-slate-500">
            <CheckCircle2 className="mb-2 h-8 w-8" />
            <span className="text-sm">No tasks found</span>
            <span className="text-xs text-slate-600">
              Try adjusting your filters
            </span>
          </div>
        </div>
      ) : (
        <div className="overflow-hidden rounded-lg border border-slate-700 bg-slate-900/50">
          <div className="overflow-x-auto">
            <table className="w-full table-fixed sm:table-auto">
              <thead>
                <tr className="border-b border-slate-700 bg-slate-800/50">
                  <th className="w-8 px-2 py-2">
                    <input
                      type="checkbox"
                      aria-label="Select all visible tasks"
                      checked={
                        tasks.length > 0 &&
                        selectedTaskIds.size === tasks.length
                      }
                      onChange={() => onToggleSelectAll(tasks)}
                      className="w-4 h-4 rounded border-slate-600 bg-slate-700 text-phosphor-500 focus:ring-phosphor-500 focus:ring-offset-0 cursor-pointer"
                    />
                  </th>
                  <th className="hidden w-8 px-2 py-2 lg:table-cell"></th>
                  <th
                    role="button"
                    tabIndex={0}
                    className="hidden w-16 cursor-pointer select-none px-3 py-2 text-left text-xs font-medium text-slate-400 hover:text-slate-200 sm:table-cell"
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
                    className="hidden w-20 cursor-pointer select-none px-3 py-2 text-left text-xs font-medium text-slate-400 hover:text-slate-200 md:table-cell"
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
                  <th className="hidden w-28 px-3 py-2 text-left text-xs font-medium text-slate-400 lg:table-cell">
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
                  <th className="hidden w-36 px-3 py-2 text-left text-xs font-medium text-slate-400 xl:table-cell">
                    Progress
                  </th>
                  <th
                    role="button"
                    tabIndex={0}
                    className="w-24 cursor-pointer select-none px-2 py-2 text-left text-xs font-medium text-slate-400 hover:text-slate-200 sm:px-3"
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
                    className="hidden w-24 cursor-pointer select-none px-3 py-2 text-left text-xs font-medium text-slate-400 hover:text-slate-200 lg:table-cell"
                    onClick={() => onSort('updated_at')}
                    onKeyDown={handleSortKeyDown('updated_at')}
                  >
                    Updated
                    <SortIndicator
                      field="updated_at"
                      currentField={sortField}
                      direction={sortDirection}
                    />
                  </th>
                  <th className="w-14 px-2 py-2 text-left text-xs font-medium text-slate-400 sm:w-16 sm:px-3">
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
          </div>

          <div className="border-t border-slate-700 bg-slate-800/30 px-4 py-2">
            <span className="text-xs text-slate-500">
              {tasks.length} task{tasks.length !== 1 ? 's' : ''}
            </span>
          </div>
        </div>
      )}
    </TaskQueryState>
  )
}
