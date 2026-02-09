'use client'

import {
  CheckCircle2,
  FastForward,
  Loader2,
  Play,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { Task, TaskStatus } from '@/lib/api'

interface TaskDetailActionsProps {
  task: Task
  onStatusChange?: (taskId: string, status: TaskStatus) => void
}

export function TaskDetailActions({
  task,
  onStatusChange,
}: TaskDetailActionsProps) {
  const isRunning = task.status === 'running'
  const isPaused = task.status === 'paused'
  const isCompleted = task.status === 'completed'

  const handleStart = () => {
    onStatusChange?.(task.id, 'running')
  }

  const handleComplete = () => {
    onStatusChange?.(task.id, 'completed')
  }

  return (
    <div className="flex items-center gap-2">
      {isPaused ? (
        <Button
          variant="outline"
          className="flex-1 gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
          onClick={handleStart}
        >
          <FastForward className="h-4 w-4" />
          Continue
        </Button>
      ) : isRunning ? (
        <>
          <Button
            variant="outline"
            className="flex-1 gap-2 border-blue-500/30 text-blue-400"
            disabled
          >
            <Loader2 className="h-4 w-4 animate-spin" />
            Running
          </Button>
          <Button
            variant="outline"
            className="gap-2 border-phosphor-500/30 text-phosphor-400 hover:bg-phosphor-500/10"
            onClick={handleComplete}
          >
            <CheckCircle2 className="h-4 w-4" />
            Complete
          </Button>
        </>
      ) : isCompleted ? (
        <Button
          variant="outline"
          className="flex-1 gap-2 border-phosphor-500/30 text-phosphor-400"
          disabled
        >
          <CheckCircle2 className="h-4 w-4" />
          Completed
        </Button>
      ) : (
        <Button
          variant="outline"
          className="flex-1 gap-2"
          onClick={handleStart}
        >
          <Play className="h-4 w-4" />
          Start
        </Button>
      )}
    </div>
  )
}
