'use client'

import {
  Bot,
  CheckCircle2,
  Edit2,
  FastForward,
  Loader2,
  Play,
  Save,
  Square,
  X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Task, TaskStatus } from '@/lib/api/tasks'

interface TaskModalActionsProps {
  task: Task
  isExecuting: boolean
  isStopping: boolean
  isTogglingAutonomous: boolean
  isEditing: boolean
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => void
  onToggleAutonomous: () => void
  onEditStart: () => void
  onEditCancel: () => void
  onEditSave: () => void
}

export function TaskModalActions({
  task,
  isExecuting,
  isStopping,
  isTogglingAutonomous,
  isEditing,
  onStartExecution,
  onStopExecution,
  onStatusChange,
  onToggleAutonomous,
  onEditStart,
  onEditCancel,
  onEditSave,
}: TaskModalActionsProps) {
  const isRunning = task.status === 'running'
  const isPaused = task.status === 'paused'
  const isCompleted = task.status === 'completed'
  const isPending = task.status === 'pending'
  const isHumanReview = task.status === 'human_review'
  const isAiReviewing = task.status === 'ai_reviewing'

  return (
    <div className="flex items-center gap-2 flex-wrap">
      {isPending && (
        <Button
          variant="outline"
          className="gap-2"
          onClick={onStartExecution}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {isExecuting ? 'Starting...' : 'Start Execution'}
        </Button>
      )}
      {isPaused && (
        <Button
          variant="outline"
          className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
          onClick={onStartExecution}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <FastForward className="h-4 w-4" />
          )}
          {isExecuting ? 'Resuming...' : 'Continue'}
        </Button>
      )}
      {isRunning && (
        <>
          <Button
            variant="outline"
            className="gap-2 border-blue-500/30 text-blue-400"
            disabled
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Executing...
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-red-500/30 text-red-400 hover:bg-red-500/10"
            onClick={onStopExecution}
            disabled={isStopping}
          >
            <Square className="h-4 w-4" />
            {isStopping ? 'Stopping at next checkpoint...' : 'Stop'}
          </Button>
        </>
      )}
      {isHumanReview && (
        <>
          <Button
            variant="outline"
            className="gap-2 border-phosphor-500/30 text-phosphor-400 hover:bg-phosphor-500/10"
            onClick={() => onStatusChange('running')}
          >
            <CheckCircle2 className="h-4 w-4" />
            Approve
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
            onClick={() => onStatusChange('pending')}
          >
            <Edit2 className="h-4 w-4" />
            Request Changes
          </Button>
        </>
      )}
      {isCompleted && (
        <Button
          variant="outline"
          className="gap-2 border-phosphor-500/30 text-phosphor-400"
          disabled
        >
          <CheckCircle2 className="h-4 w-4" />
          Completed
        </Button>
      )}
      {isAiReviewing && (
        <Button
          variant="outline"
          className="gap-2 border-cyan-500/30 text-cyan-400"
          disabled
        >
          <Loader2 className="h-4 w-4 animate-spin" />
          AI Reviewing...
        </Button>
      )}
      {/* Autonomous Toggle */}
      <Button
        variant="outline"
        className={`gap-2 ${
          task.autonomous
            ? 'border-purple-500/30 text-purple-400 bg-purple-500/10'
            : 'border-slate-600 text-slate-400'
        }`}
        onClick={onToggleAutonomous}
        disabled={isTogglingAutonomous || isRunning}
        title={
          task.autonomous
            ? 'Autonomous execution enabled - task will be picked up by auto-exec when enabled'
            : 'Click to enable autonomous execution for this task'
        }
      >
        {isTogglingAutonomous ? (
          <Loader2 className="h-4 w-4 animate-spin" />
        ) : (
          <Bot className="h-4 w-4" />
        )}
        {task.autonomous ? 'Autonomous' : 'Manual'}
      </Button>
      <div className="ml-auto flex items-center gap-2">
        {isEditing ? (
          <>
            <Button variant="outline" size="sm" onClick={onEditCancel}>
              <X className="h-4 w-4" />
            </Button>
            <Button variant="primary" size="sm" onClick={onEditSave}>
              <Save className="h-4 w-4" />
            </Button>
          </>
        ) : (
          <Button variant="outline" size="sm" onClick={onEditStart}>
            <Edit2 className="h-4 w-4" />
          </Button>
        )}
      </div>
    </div>
  )
}
