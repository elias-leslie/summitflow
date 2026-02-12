import { SortableContext, verticalListSortingStrategy } from '@dnd-kit/sortable'
import {
  CircleCheck,
  Clock,
  Lightbulb,
  PenLine,
  ShieldAlert,
  Zap,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import type { Task } from '@/lib/api'
import type { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import { TaskCard } from './TaskCard'
import {
  columnColorClasses,
  type KanbanColumn as KanbanColumnType,
} from './columnConfig'

const COLUMN_ICONS: Record<string, LucideIcon> = {
  lightbulb: Lightbulb,
  'pen-line': PenLine,
  clock: Clock,
  zap: Zap,
  'shield-alert': ShieldAlert,
  'circle-check': CircleCheck,
}

// ============================================================================
// Kanban Column Component
// ============================================================================

interface KanbanColumnProps {
  column: KanbanColumnType
  tasks: Task[]
  onTaskClick?: (task: Task) => void
  onExecuteNow?: (taskId: string) => void
  onDelete?: (taskId: string) => void
  executingTaskId?: string | null
  runningTaskId?: string | null
  executionHook?: ReturnType<typeof useExecutionWebSocket>
}

export function KanbanColumn({
  column,
  tasks,
  onTaskClick,
  onExecuteNow,
  onDelete,
  executingTaskId,
  runningTaskId,
  executionHook,
}: KanbanColumnProps) {
  const colors = columnColorClasses[column.color] || columnColorClasses.slate
  const IconComponent = column.icon ? COLUMN_ICONS[column.icon] : null

  return (
    <div
      className={`flex-shrink-0 w-[85vw] sm:w-[280px] md:w-auto md:flex-1 md:min-w-[220px] md:max-w-[300px] flex flex-col rounded-lg border ${colors.border} ${colors.bg} snap-start md:snap-align-none`}
    >
      {/* Column Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <h3
          className={`text-sm font-medium flex items-center gap-1.5 ${colors.header}`}
        >
          {IconComponent && (
            <IconComponent
              className={`w-4 h-4${column.icon === 'zap' ? ' animate-pulse' : ''}`}
            />
          )}
          {column.title}
        </h3>
        <span className="text-xs mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
          {tasks.length}
        </span>
      </div>

      {/* Column Content */}
      <div className="flex-1 p-2 overflow-y-auto min-h-[200px] max-h-[calc(100vh-300px)]">
        <SortableContext
          items={tasks.map((t) => t.id)}
          strategy={verticalListSortingStrategy}
        >
          <div className="space-y-2">
            {tasks.length > 0 ? (
              tasks.map((task) => {
                const isRunningTask = task.id === runningTaskId
                return (
                  <TaskCard
                    key={task.id}
                    task={task}
                    onClick={() => onTaskClick?.(task)}
                    onExecuteNow={
                      column.id === 'ideas' ? onExecuteNow : undefined
                    }
                    onDelete={onDelete}
                    isExecuting={executingTaskId === task.id}
                    execution={
                      isRunningTask ? executionHook?.execution : undefined
                    }
                    wsConnected={
                      isRunningTask ? executionHook?.connected : false
                    }
                    onStopExecution={
                      isRunningTask ? executionHook?.sendStop : undefined
                    }
                    onSendMessage={
                      isRunningTask ? executionHook?.sendMessage : undefined
                    }
                  />
                )
              })
            ) : (
              <div className="flex items-center justify-center h-24 text-xs text-slate-600 italic">
                No tasks
              </div>
            )}
          </div>
        </SortableContext>
      </div>
    </div>
  )
}
