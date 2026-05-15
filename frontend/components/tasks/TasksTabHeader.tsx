'use client'

import { RefreshCw, Trash2, Zap } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { TaskFilters, type TaskFilterValues } from './TaskFilters'

interface TasksTabHeaderProps {
  projectId: string
  filters: TaskFilterValues
  onFiltersChange: (filters: TaskFilterValues) => void
  selectedCount: number
  isFetching: boolean
  isQueueing: boolean
  onRefresh: () => void
  onBulkExecute: () => void
  onBulkDelete: () => void
}

export function TasksTabHeader({
  projectId,
  filters,
  onFiltersChange,
  selectedCount,
  isFetching,
  isQueueing,
  onRefresh,
  onBulkExecute,
  onBulkDelete,
}: TasksTabHeaderProps) {
  return (
    <div className="flex items-center justify-between">
      <TaskFilters
        projectId={projectId}
        filters={filters}
        onChange={onFiltersChange}
      />
      <div className="flex items-center gap-2">
        {selectedCount > 0 && (
          <>
            <Button
              size="sm"
              variant="outline"
              onClick={onBulkExecute}
              disabled={isQueueing}
              className="border-yellow-500/50 text-yellow-300 hover:bg-yellow-500/20"
            >
              <Zap className="w-4 h-4 mr-1" />
              Queue {selectedCount}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={onBulkDelete}
              className="border-red-600 text-red-400 hover:bg-red-500/20"
            >
              <Trash2 className="w-4 h-4 mr-1" />
              Delete {selectedCount} task{selectedCount !== 1 ? 's' : ''}
            </Button>
          </>
        )}
        <Button
          size="sm"
          variant="outline"
          onClick={onRefresh}
          disabled={isFetching}
        >
          <RefreshCw className={cn('w-4 h-4', isFetching && 'animate-spin')} />
        </Button>
      </div>
    </div>
  )
}
