'use client'

import { useDroppable } from '@dnd-kit/core'
import { SortableContext, rectSortingStrategy } from '@dnd-kit/sortable'
import { ChevronRight } from 'lucide-react'
import { AnimatePresence, motion } from 'motion/react'

import type { Task } from '@/lib/api'
import type { useExecutionWebSocket } from '@/hooks/useExecutionWebSocket'
import { TaskCard } from './TaskCard'
import { EyeIcon, LightbulbIcon, SparklesIcon } from './ColumnIcons'
import {
  columnColorClasses,
  type KanbanColumn as KanbanColumnType,
} from './columnConfig'

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

  const { setNodeRef, isOver } = useDroppable({ id: column.id })

  const showDropHint = isDragging && isCollapsed && isOver

  return (
    <div
      ref={setNodeRef}
      className={`rounded-lg border transition-colors ${
        showDropHint
          ? colors.dropIndicator
          : `${colors.border} ${colors.bg}`
      }`}
    >
      {/* Row Header — always visible, clickable */}
      <button
        type="button"
        onClick={onToggle}
        className={`flex w-full items-center gap-2 px-4 py-2.5 text-left transition-colors hover:bg-white/5 rounded-lg ${
          !isCollapsed ? 'border-b border-slate-800 rounded-b-none' : ''
        }`}
      >
        <motion.span
          animate={{ rotate: isCollapsed ? 0 : 90 }}
          transition={{ duration: 0.15 }}
          className="flex-shrink-0"
        >
          <ChevronRight className={`h-4 w-4 ${colors.header}`} />
        </motion.span>

        {column.icon === 'lightbulb' && (
          <LightbulbIcon className={`w-4 h-4 ${colors.header}`} />
        )}
        {column.icon === 'sparkles' && (
          <SparklesIcon className={`w-4 h-4 ${colors.header} animate-pulse`} />
        )}
        {column.icon === 'eye' && (
          <EyeIcon className={`w-4 h-4 ${colors.header}`} />
        )}

        <span className={`text-sm font-medium ${colors.header}`}>
          {column.title}
        </span>

        <span className="text-xs mono text-slate-500 bg-slate-800 px-2 py-0.5 rounded">
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
                  <div className="flex items-center justify-center h-16 text-xs text-slate-600 italic">
                    No tasks
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
