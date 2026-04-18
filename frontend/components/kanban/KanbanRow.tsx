'use client'

import { useDroppable } from '@dnd-kit/core'
import { rectSortingStrategy, SortableContext } from '@dnd-kit/sortable'
import clsx from 'clsx'
import type { LucideIcon } from 'lucide-react'
import {
  ChevronRight,
  CircleCheck,
  Clock,
  Lightbulb,
  PenLine,
  ShieldAlert,
  Zap,
} from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'
import type { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import type { Task } from '@/lib/api'
import {
  columnColorClasses,
  type KanbanColumn as KanbanColumnType,
} from './columnConfig'
import { TaskCard } from './TaskCard'

const COLUMN_ICONS: Record<string, LucideIcon> = {
  lightbulb: Lightbulb,
  'pen-line': PenLine,
  clock: Clock,
  zap: Zap,
  'shield-alert': ShieldAlert,
  'circle-check': CircleCheck,
}

interface KanbanRowProps {
  column: KanbanColumnType
  tasks: Task[]
  isCollapsed: boolean
  isDragging: boolean
  onToggle: () => void
  onTaskClick?: (task: Task) => void
  onExecuteNow?: (taskId: string) => void
  onDelete?: (taskId: string) => void
  executingTaskId?: string | null
  runningTaskId?: string | null
  executionHook?: ReturnType<typeof useExecutionWebSocket>
}

export function KanbanRow({
  column,
  tasks,
  isCollapsed,
  isDragging,
  onToggle,
  onTaskClick,
  onExecuteNow,
  onDelete,
  executingTaskId,
  runningTaskId,
  executionHook,
}: KanbanRowProps) {
  const colors = columnColorClasses[column.color] || columnColorClasses.slate
  const IconComponent = column.icon ? COLUMN_ICONS[column.icon] : null

  const { setNodeRef, isOver } = useDroppable({ id: column.id })

  const showDropHint = isDragging && isCollapsed && isOver

  return (
    <div
      ref={setNodeRef}
      className={clsx(
        'rounded-lg border transition-colors',
        showDropHint ? colors.dropIndicator : [colors.border, colors.bg],
      )}
    >
      {/* Row Header — always visible, clickable */}
      <button
        type="button"
        onClick={onToggle}
        className={clsx(
          'flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-slate-800/30 rounded-lg',
          !isCollapsed && 'border-b border-slate-800/60 rounded-b-none',
        )}
      >
        <motion.span
          animate={{ rotate: isCollapsed ? 0 : 90 }}
          transition={{ duration: 0.15 }}
          className="flex-shrink-0"
        >
          <ChevronRight className={clsx('h-4 w-4', colors.header)} />
        </motion.span>

        {IconComponent && (
          <IconComponent
            className={clsx(
              'w-4 h-4',
              colors.header,
              column.icon === 'zap' && 'animate-pulse',
            )}
          />
        )}

        <span className={clsx('display text-sm font-semibold', colors.header)}>
          {column.title}
        </span>

        <span className="text-xs mono text-slate-500 bg-slate-800/80 px-2 py-0.5 rounded-md tabular-nums">
          {tasks.length}
        </span>

        {showDropHint && (
          <span className="ml-auto text-xs text-slate-400 animate-pulse">
            Drop to add here
          </span>
        )}
      </button>

      {/* Row Body — collapsible grid */}
      <AnimatePresence initial={false}>
        {!isCollapsed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.2, ease: 'easeInOut' }}
            className="overflow-hidden"
          >
            <SortableContext
              items={tasks.map((t) => t.id)}
              strategy={rectSortingStrategy}
            >
              <div className="p-3">
                {tasks.length > 0 ? (
                  <div className="grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(300px,100%),1fr))]">
                    {tasks.map((task) => {
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
                            isRunningTask
                              ? executionHook?.sendMessage
                              : undefined
                          }
                        />
                      )
                    })}
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-16 gap-2 text-xs text-slate-600">
                    <span className="inline-block w-1 h-1 rounded-full bg-slate-700" />
                    No tasks yet
                  </div>
                )}
              </div>
            </SortableContext>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  )
}
