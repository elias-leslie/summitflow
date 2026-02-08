'use client'

import { useSortable } from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  ChevronDown,
  ChevronUp,
  ExternalLink,
  GitPullRequest,
  GripVertical,
  Lightbulb,
  Link2,
  Loader2,
  Trash2,
  Zap,
} from 'lucide-react'
import { AnimatePresence } from 'motion/react'
import { useState } from 'react'

import type { Task, TaskStatus } from '@/lib/api'
import {
  getPriorityClasses,
  getTaskStatusCardConfig,
  getTaskTypeConfigSmall,
} from '@/lib/task-config'
import { ExecutionPanel, type ExecutionState } from './ExecutionPanel'

const EXECUTION_PHASES = [
  'Triage',
  'Plan',
  'Queue',
  'Execute',
  'Review',
] as const
type ExecutionPhase = (typeof EXECUTION_PHASES)[number]

function getPhaseFromStatus(status: TaskStatus): ExecutionPhase | null {
  switch (status) {
    case 'pending':
      return 'Triage'
    case 'paused':
    case 'blocked':
      return 'Plan'
    case 'queue':
      return 'Queue'
    case 'running':
      return 'Execute'
    case 'ai_reviewing':
    case 'pr_created':
      return 'Review'
    default:
      return null
  }
}

function StepProgressIndicator({ status }: { status: TaskStatus }) {
  const currentPhase = getPhaseFromStatus(status)
  if (!currentPhase) return null

  const currentIndex = EXECUTION_PHASES.indexOf(currentPhase)

  return (
    <div className="flex items-center gap-1 text-xs">
      {EXECUTION_PHASES.map((phase, index) => {
        const isActive = index === currentIndex
        const isPast = index < currentIndex
        return (
          <div key={phase} className="flex items-center gap-1">
            {index > 0 && (
              <div
                className={`w-2 h-px ${isPast ? 'bg-phosphor-500' : 'bg-slate-600'}`}
              />
            )}
            <span
              className={`px-1.5 py-0.5 rounded text-[10px] font-medium ${
                isActive
                  ? 'bg-phosphor-500/20 text-phosphor-400 border border-phosphor-500/30'
                  : isPast
                    ? 'bg-slate-700 text-slate-300'
                    : 'bg-slate-800 text-slate-500'
              }`}
            >
              {phase}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ============================================================================
// Types
// ============================================================================

interface TaskCardProps {
  task: Task
  onClick?: () => void
  onExecuteNow?: (taskId: string) => void
  isExecuting?: boolean
  onDelete?: (taskId: string) => void
  // Execution panel props
  execution?: ExecutionState
  wsConnected?: boolean
  onStopExecution?: () => void
  onSendMessage?: (message: string) => void
}

// Check if task is a crowdsourced idea
function isCrowdsourcedIdea(task: Task): boolean {
  return (
    task.status === 'pending' &&
    task.labels?.some((label) => label.toLowerCase() === 'crowdsourced')
  )
}

// ============================================================================
// Task Card Component
// ============================================================================

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

  const typeConfig = getTaskTypeConfigSmall(task.task_type)
  const statusConfig = getTaskStatusCardConfig(task.status)
  const isIdea = isCrowdsourcedIdea(task)

  // Show expand button for running or ai_reviewing tasks
  const canExpand = task.status === 'running' || task.status === 'ai_reviewing'

  const handleExpandToggle = (e: React.MouseEvent) => {
    e.stopPropagation()
    setExpanded(!expanded)
  }

  // Capability context for criteria progress
  const capability = task.capability
  const hasCriteria = capability && capability.criteria_total > 0
  const allPassed =
    hasCriteria && capability.criteria_passed === capability.criteria_total

  const isRunning = task.status === 'running'
  const currentStep = execution?.currentStep

  return (
    <div
      ref={setNodeRef}
      style={style}
      data-testid={`task-card-${task.id}`}
      className={`group relative rounded-lg border bg-slate-900/80 p-3 shadow-sm hover:border-slate-600 hover:bg-slate-850 transition-colors cursor-pointer ${
        isRunning
          ? 'border-phosphor-500/50 shadow-phosphor-500/20 shadow-lg animate-pulse-glow'
          : 'border-slate-700'
      }`}
      onClick={onClick}
    >
      {/* Drag Handle */}
      <div
        {...attributes}
        {...listeners}
        className="absolute left-1 top-3 opacity-0 group-hover:opacity-100 transition-opacity cursor-grab active:cursor-grabbing"
        onClick={(e) => e.stopPropagation()}
      >
        <GripVertical className="h-4 w-4 text-slate-500" />
      </div>

      {/* Delete Button */}
      {onDelete && (
        <button
          onClick={(e) => {
            e.stopPropagation()
            onDelete(task.id)
          }}
          className="absolute right-2 top-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 rounded hover:bg-red-500/20 text-slate-500 hover:text-red-400"
          title="Delete task"
        >
          <Trash2 className="h-3.5 w-3.5" />
        </button>
      )}

      {/* Card Content */}
      <div className="pl-4">
        {/* Header: Type Icon + ID + Priority + Status */}
        <div className="flex items-center justify-between gap-2 mb-1">
          <div className="flex items-center gap-2">
            {/* Type Icon */}
            <span className={typeConfig.className} title={task.task_type}>
              {typeConfig.icon}
            </span>
            {/* Task ID */}
            <span className="text-xs mono text-slate-500">{task.id}</span>
            {/* Priority Badge */}
            <span
              className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${getPriorityClasses(task.priority)}`}
            >
              P{task.priority}
            </span>
            {/* Running Indicator */}
            {task.status === 'running' && statusConfig?.icon && (
              <span
                className={`flex items-center ${statusConfig.className}`}
                title={statusConfig.title}
              >
                {statusConfig.icon}
              </span>
            )}
          </div>
        </div>

        {/* Title */}
        <h4 className="text-sm font-medium text-white leading-tight mb-2 line-clamp-2">
          {task.title}
        </h4>

        {/* Current Step from WebSocket execution event */}
        {isRunning && currentStep && (
          <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-blue-500/10 border border-blue-500/20">
            <Loader2 className="h-3 w-3 animate-spin text-blue-400 shrink-0" />
            <span className="text-xs text-blue-300 truncate">
              {currentStep}
            </span>
          </div>
        )}

        {/* Step Progress Indicator showing phase */}
        {canExpand && <StepProgressIndicator status={task.status} />}

        {/* AI Review Status Bar - shown for relevant states */}
        {(task.status === 'ai_reviewing' ||
          task.status === 'pr_created') && (
          <div className="flex items-center gap-2 mb-2 py-1.5 px-2 -mx-1 rounded bg-slate-800/50">
            <span
              className={`flex items-center gap-1.5 ${statusConfig?.className || ''}`}
            >
              {statusConfig?.icon}
              <span className="text-xs font-medium">{statusConfig?.title}</span>
            </span>
            {task.pull_request_url && (
              <a
                href={task.pull_request_url}
                target="_blank"
                rel="noopener noreferrer"
                className="ml-auto flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
                onClick={(e) => e.stopPropagation()}
              >
                <GitPullRequest className="h-3 w-3" />
                <span>PR</span>
                <ExternalLink className="h-2.5 w-2.5" />
              </a>
            )}
          </div>
        )}

        {/* Capability Link or Standalone Indicator */}
        <div className="flex items-center justify-between">
          {capability ? (
            <div className="flex items-center gap-1.5">
              <Link2 className="h-3 w-3 text-slate-500" />
              <span className="text-xs text-phosphor-400 mono">
                {capability.capability_id}
              </span>
              {hasCriteria && (
                <span
                  className={`text-xs mono ${allPassed ? 'text-phosphor-400' : 'text-slate-400'}`}
                >
                  ({capability.criteria_passed}/{capability.criteria_total})
                </span>
              )}
            </div>
          ) : task.pull_request_url &&
            task.status !== 'ai_reviewing' &&
            task.status !== 'pr_created' ? (
            <a
              href={task.pull_request_url}
              target="_blank"
              rel="noopener noreferrer"
              className="flex items-center gap-1 text-xs text-violet-400 hover:text-violet-300 transition-colors"
              onClick={(e) => e.stopPropagation()}
            >
              <GitPullRequest className="h-3 w-3" />
              <span>View PR</span>
              <ExternalLink className="h-2.5 w-2.5" />
            </a>
          ) : (
            <span className="text-xs text-slate-600 italic">Standalone</span>
          )}

          {/* Criteria Progress Dots for capability-linked tasks */}
          {hasCriteria && (
            <div className="flex items-center gap-0.5">
              {Array.from({ length: capability?.criteria_total }).map(
                (_, i) => (
                  <div
                    key={i}
                    className={`h-1.5 w-1.5 rounded-full ${
                      i < capability?.criteria_passed
                        ? 'bg-phosphor-500'
                        : 'bg-slate-600'
                    }`}
                  />
                ),
              )}
            </div>
          )}
        </div>

        {/* Execute Now button for crowdsourced ideas */}
        {isIdea && onExecuteNow && (
          <div className="mt-3 pt-2 border-t border-slate-700/50">
            <button
              onClick={(e) => {
                e.stopPropagation()
                onExecuteNow(task.id)
              }}
              disabled={isExecuting}
              className="flex items-center justify-center gap-1.5 w-full px-3 py-1.5 text-xs font-medium rounded bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30 border border-yellow-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {isExecuting ? (
                <>
                  <Loader2 className="h-3 w-3 animate-spin" />
                  Executing...
                </>
              ) : (
                <>
                  <Zap className="h-3 w-3" />
                  Execute Now
                </>
              )}
            </button>
          </div>
        )}

        {/* Idea indicator badge */}
        {isIdea && (
          <div className="absolute top-2 right-2">
            <Lightbulb className="h-4 w-4 text-yellow-400" />
          </div>
        )}

        {/* Expand/Collapse button for running tasks */}
        {canExpand && (
          <button
            onClick={handleExpandToggle}
            className="mt-3 flex items-center justify-center gap-1 w-full py-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="h-3 w-3" />
                Hide execution details
              </>
            ) : (
              <>
                <ChevronDown className="h-3 w-3" />
                Show execution details
              </>
            )}
          </button>
        )}

        {/* Execution Panel (animated expand/collapse) */}
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

// ============================================================================
// Drag Overlay Card (for visual feedback during drag)
// ============================================================================

interface DragOverlayTaskCardProps {
  task: Task
}

export function DragOverlayTaskCard({ task }: DragOverlayTaskCardProps) {
  const typeConfig = getTaskTypeConfigSmall(task.task_type)

  return (
    <div className="rounded-lg border border-phosphor-500 bg-slate-900 p-3 shadow-xl shadow-phosphor-500/20 rotate-2 max-w-[300px]">
      <div className="flex items-center gap-2 mb-1">
        <span className={typeConfig.className}>{typeConfig.icon}</span>
        <span className="text-xs mono text-slate-500">{task.id}</span>
        <span
          className={`text-xs px-1.5 py-0.5 rounded border mono font-medium ${getPriorityClasses(task.priority)}`}
        >
          P{task.priority}
        </span>
      </div>
      <h4 className="text-sm font-medium text-white line-clamp-2">
        {task.title}
      </h4>
    </div>
  )
}
