'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import { GripVertical } from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useState } from 'react'

import type { Task } from '@/lib/api'
import { ExecutionPanel, type ExecutionState } from './ExecutionPanel'
import { TaskCardHeader } from './TaskCardHeader'
import { TaskCardBody } from './TaskCardBody'
import { TaskCardActions } from './TaskCardActions'
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
      className={`group relative rounded-lg border bg-slate-900/80 p-3 shadow-sm hover:border-slate-600 hover:bg-slate-850 transition-all duration-200 cursor-pointer ${
        isRunning
          ? 'border-phosphor-500/50 shadow-phosphor-500/20 shadow-lg animate-[pulse-glow_2s_ease-in-out_infinite]'
          : 'border-slate-700 hover:translate-y-[-1px]'
      }`}
      onClick={onClick}
    >
      <div
        {...attributes}
        {...listeners}
        className="absolute left-1 top-3 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

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

      <div className="pl-4">
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
              <ExecutionPanel
                execution={execution}
                connected={wsConnected}
                onStop={onStopExecution}
                onSendMessage={onSendMessage}
              />
            )}
        </AnimatePresence>
      </div>
    </div>
  )
}
