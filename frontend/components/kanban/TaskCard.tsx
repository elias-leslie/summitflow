'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import clsx from 'clsx'
import { GripVertical } from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useState } from 'react'
import type { Task } from '@/lib/api'
import { ExecutionPanel, type ExecutionState } from './ExecutionPanel'
import { TaskCardActions } from './TaskCardActions'
import { TaskCardBody } from './TaskCardBody'
import { TaskCardHeader } from './TaskCardHeader'
import { isCrowdsourcedIdea } from './task-card-utils'

// Re-export for backward compatibility
export { DragOverlayTaskCard } from './DragOverlayTaskCard'

interface TaskCardProps {
  task: Task
  onClick?: () => void
  onExecuteNow?: (taskId: string) => void
  isExecuting?: boolean
  onDelete?: (taskId: string) => void
  execution?: ExecutionState
  wsConnected?: boolean
  onStopExecution?: () => void
  onSendMessage?: (message: string) => void
}

export function TaskCard({
  task,
  onClick,
  onExecuteNow,
  isExecuting,
  onDelete,
  execution,
  wsConnected = false,
  onStopExecution,
  onSendMessage,
}: TaskCardProps) {
  const [expanded, setExpanded] = useState(false)
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: task.id })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  }

  const isIdea = isCrowdsourcedIdea(task)
  const canExpand = task.status === 'running'
  const isRunning = task.status === 'running'
  const currentStep = execution?.currentStep

  const handleExpandToggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    setExpanded(!expanded)
  }

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`task-card-${task.id}`}
      className={clsx(
        'group relative rounded-xl border bg-[linear-gradient(180deg,rgba(18,12,28,0.92),rgba(10,7,17,0.94))] p-3 shadow-[0_12px_24px_-20px_rgba(0,0,0,0.8)] hover:border-slate-600/90 hover:bg-[linear-gradient(180deg,rgba(22,15,34,0.95),rgba(12,9,20,0.96))] transition-all duration-200',
        isRunning
          ? 'border-phosphor-500/50 shadow-[0_0_20px_rgba(0,245,255,0.12)] animate-[pulse-glow_2s_ease-in-out_infinite] motion-reduce:animate-none'
          : 'border-slate-700/80 hover:translate-y-[-2px] hover:shadow-[0_16px_32px_-20px_rgba(0,0,0,0.9)] motion-reduce:hover:translate-y-0',
      )}
    >
      <div
        {...attributes}
        {...listeners}
        className="absolute left-1 top-3 z-20 cursor-grab opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100 active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

      {onClick && (
        <button
          type="button"
          aria-label={`Open task ${task.id}: ${task.title}`}
          onClick={onClick}
          className="absolute inset-0 z-0 cursor-pointer rounded-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-phosphor-500/70"
        />
      )}

      <TaskCardActions
        isIdea={isIdea}
        canExpand={canExpand}
        expanded={expanded}
        isExecuting={isExecuting}
        taskId={task.id}
        onDelete={onDelete}
        onExecuteNow={onExecuteNow}
        onExpandToggle={handleExpandToggle}
      />

      <div className="pointer-events-none relative z-0 pl-4">
        <TaskCardHeader task={task} />
        <TaskCardBody
          task={task}
          currentStep={currentStep}
          canExpand={canExpand}
        />

        <AnimatePresence>
          {expanded &&
            canExpand &&
            execution &&
            onStopExecution &&
            onSendMessage && (
              <div className="pointer-events-auto relative z-20">
                <ExecutionPanel
                  execution={execution}
                  connected={wsConnected}
                  onStop={onStopExecution}
                  onSendMessage={onSendMessage}
                />
              </div>
            )}
        </AnimatePresence>
      </div>
    </div>
  )
}
