'use client'

import {
  CheckCircle2,
  Edit2,
  FastForward,
  Loader2,
  Play,
  Square,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import type { TaskStatus } from '@/lib/api/tasks'

interface StatusActionButtonsProps {
  status: TaskStatus
  isExecuting: boolean
  isStopping: boolean
  onStartExecution: () => void
  onStopExecution: () => void
  onStatusChange: (status: TaskStatus) => Promise<void>
}

export function StatusActionButtons({
  status,
  isExecuting,
  isStopping,
  onStartExecution,
  onStopExecution,
  onStatusChange,
}: StatusActionButtonsProps) {
  const isPending = status === 'pending'
  const isPaused = status === 'paused'
  const isRunning = status === 'running'
  const isBlocked = status === 'blocked'
  const isCompleted = status === 'completed'
  const isAiReviewing = status === 'ai_reviewing'

  return (
    <>
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
      {isBlocked && (
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
    </>
  )
}
