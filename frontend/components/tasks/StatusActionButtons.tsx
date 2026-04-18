'use client'

import { CheckCircle2, Loader2, Play, Square } from 'lucide-react'
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
}: StatusActionButtonsProps) {
  const isPending = status === 'pending'
  const isRunning = status === 'running'
  const isCompleted = status === 'completed'
  const isFailed = status === 'failed'

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
      {isFailed && (
        <Button
          variant="outline"
          className="gap-2 border-amber-500/30 text-amber-400 hover:bg-amber-500/10"
          onClick={onStartExecution}
          disabled={isExecuting}
        >
          {isExecuting ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Play className="h-4 w-4" />
          )}
          {isExecuting ? 'Retrying...' : 'Retry'}
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
    </>
  )
}
