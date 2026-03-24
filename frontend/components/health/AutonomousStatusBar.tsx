'use client'

import clsx from 'clsx'
import { Badge } from '@/components/ui/badge'
import type { Autonomous } from './PipelineTypes'

interface AutonomousStatusBarProps {
  autonomous: Autonomous
}

export function AutonomousStatusBar({ autonomous }: AutonomousStatusBarProps) {
  const { running_count, max_concurrent, queue_depth, next_scheduled } = autonomous
  const availableSlots = Math.max(max_concurrent - running_count, 0)
  const atCapacity = running_count >= max_concurrent
  const hasBacklog = queue_depth > 0

  // Format next scheduled time
  const formatNextScheduled = (timestamp: string | null) => {
    if (!timestamp) return 'None scheduled'
    const date = new Date(timestamp)
    const now = new Date()
    const diffMs = date.getTime() - now.getTime()
    const diffMins = Math.floor(diffMs / 60000)

    if (diffMins < 0) return 'Overdue'
    if (diffMins < 60) return `In ${diffMins}m`
    if (diffMins < 1440) return `In ${Math.floor(diffMins / 60)}h ${diffMins % 60}m`
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
  }

  const statusLabel = running_count > 0
    ? atCapacity
      ? 'At capacity'
      : 'Running'
    : hasBacklog
      ? 'Queued'
      : 'Idle'

  const statusTone =
    running_count > 0 ? 'bg-phosphor-500 animate-pulse' : hasBacklog ? 'bg-amber-500' : 'bg-slate-600'

  return (
    <div className="card rounded-xl p-4">
      <div className="flex items-center justify-between gap-4">
        <div className="flex flex-wrap items-center gap-4">
          <h3 className="text-sm font-semibold text-slate-300 display">Autonomous Execution</h3>

          {/* Running/Concurrency indicator */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Running:</span>
            <Badge variant={running_count > 0 ? 'phosphor' : 'slate'}>
              {running_count}/{max_concurrent}
            </Badge>
            <span className="text-2xs text-slate-500">
              {availableSlots} slot{availableSlots === 1 ? '' : 's'} free
            </span>
          </div>

          {/* Queue depth */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Queued:</span>
            <Badge variant={queue_depth > 0 ? 'amber' : 'slate'}>
              {queue_depth}
            </Badge>
          </div>

          {/* Next scheduled */}
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Next:</span>
            <span className="text-xs text-slate-400 tabular-nums">
              {formatNextScheduled(next_scheduled)}
            </span>
          </div>
        </div>

        {/* Status indicator */}
        <div className="flex items-center gap-2">
          <span className={clsx('w-2 h-2 rounded-full', statusTone)} />
          <span className="text-xs text-slate-500">
            {statusLabel}
          </span>
        </div>
      </div>
    </div>
  )
}
