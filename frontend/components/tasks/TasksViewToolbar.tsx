'use client'

import { Kanban, List, Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ViewMode } from './hooks/useViewMode'

interface TasksViewToolbarProps {
  viewMode: ViewMode
  onViewModeChange: (mode: ViewMode) => void
  onNewTask: () => void
}

export function TasksViewToolbar({
  viewMode,
  onViewModeChange,
  onNewTask,
}: TasksViewToolbarProps) {
  return (
    <div className="flex items-center justify-between">
      {/* Board | Table toggle */}
      <div className="flex items-center gap-0.5 rounded-lg bg-slate-800/60 border border-slate-700/50 p-0.5">
        <button
          type="button"
          onClick={() => onViewModeChange('board')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
            viewMode === 'board'
              ? 'bg-phosphor-500/15 text-phosphor-400 shadow-sm'
              : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
          )}
        >
          <Kanban className="w-3.5 h-3.5" />
          Board
        </button>
        <button
          type="button"
          onClick={() => onViewModeChange('table')}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-all duration-200',
            viewMode === 'table'
              ? 'bg-phosphor-500/15 text-phosphor-400 shadow-sm'
              : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800/50',
          )}
        >
          <List className="w-3.5 h-3.5" />
          Table
        </button>
      </div>

      {/* New Task button */}
      <Button variant="primary" size="sm" onClick={onNewTask} data-testid="new-task-button">
        <Plus className="w-4 h-4 mr-1" />
        New Task
      </Button>
    </div>
  )
}
