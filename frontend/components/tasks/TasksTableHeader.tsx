/**
 * Tasks Table Header - Filters and controls for the tasks table
 */

import { ListTodo, Plus, RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { TaskType } from '@/lib/api'
import { cn } from '@/lib/utils'

interface TasksTableHeaderProps {
  statusFilter: 'all' | 'pending' | 'completed'
  typeFilter: TaskType | 'all'
  onStatusFilterChange: (filter: 'all' | 'pending' | 'completed') => void
  onTypeFilterChange: (filter: TaskType | 'all') => void
  onRefresh: () => void
  onCreateTask: () => void
  isLoading: boolean
}

export function TasksTableHeader({
  statusFilter,
  typeFilter,
  onStatusFilterChange,
  onTypeFilterChange,
  onRefresh,
  onCreateTask,
  isLoading,
}: TasksTableHeaderProps) {
  return (
    <div className="p-4 border-b border-slate-700">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <ListTodo className="w-5 h-5 text-slate-400" />
          <h3 className="font-medium text-white">All Tasks</h3>
        </div>
        <div className="flex items-center gap-2">
          {/* Status Filter */}
          <div className="flex items-center gap-1 bg-slate-800 rounded-lg p-1">
            {(['pending', 'completed', 'all'] as const).map((s) => (
              <button
                key={s}
                onClick={() => onStatusFilterChange(s)}
                className={cn(
                  'px-3 py-1 text-xs rounded transition-colors',
                  statusFilter === s
                    ? 'bg-slate-700 text-white'
                    : 'text-slate-400 hover:text-white',
                )}
              >
                {s === 'all' ? 'All' : s === 'pending' ? 'Active' : 'Done'}
              </button>
            ))}
          </div>

          {/* Type Filter */}
          <select
            value={typeFilter}
            onChange={(e) =>
              onTypeFilterChange(e.target.value as TaskType | 'all')
            }
            className="px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded text-white"
          >
            <option value="all">All Types</option>
            <option value="feature">Features</option>
            <option value="bug">Bugs</option>
            <option value="task">Tasks</option>
          </select>

          {/* Refresh */}
          <Button
            size="sm"
            variant="outline"
            onClick={onRefresh}
            disabled={isLoading}
          >
            <RefreshCw className={cn('w-4 h-4', isLoading && 'animate-spin')} />
          </Button>

          {/* Create */}
          <Button size="sm" onClick={onCreateTask}>
            <Plus className="w-4 h-4 mr-1" />
            New
          </Button>
        </div>
      </div>
    </div>
  )
}
