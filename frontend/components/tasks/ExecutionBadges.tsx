'use client'

import clsx from 'clsx'
import {
  Ban,
  CheckCircle2,
  Clock,
  DollarSign,
  Loader2,
  RefreshCw,
  XCircle,
  Zap,
} from 'lucide-react'

import type { Task, TaskStatus } from '@/lib/api/tasks'

// ============================================================================
// Types
// ============================================================================

interface ExecutionBadgesProps {
  task: Task
  /** Show compact badges (smaller, fewer details) */
  compact?: boolean
  /** Optional class name */
  className?: string
}

interface ExecutionMetadata {
  model?: string
  retryCount?: number
  cost?: number
  duration?: number
}

// ============================================================================
// Status Icon Configuration
// ============================================================================

const statusIcons: Record<
  TaskStatus,
  { icon: React.ReactNode; color: string; bg: string }
> = {
  pending: {
    icon: <Clock className="h-3 w-3" />,
    color: 'text-slate-400',
    bg: 'bg-slate-500/20',
  },
  running: {
    icon: <Loader2 className="h-3 w-3 animate-spin" />,
    color: 'text-blue-400',
    bg: 'bg-blue-500/20',
  },
  completed: {
    icon: <CheckCircle2 className="h-3 w-3" />,
    color: 'text-phosphor-400',
    bg: 'bg-phosphor-500/20',
  },
  failed: {
    icon: <XCircle className="h-3 w-3" />,
    color: 'text-red-400',
    bg: 'bg-red-500/20',
  },
  cancelled: {
    icon: <Ban className="h-3 w-3" />,
    color: 'text-slate-400',
    bg: 'bg-slate-500/20',
  },
}

// ============================================================================
// Model name formatting
// ============================================================================

function formatModelName(model?: string): string | null {
  if (!model) return null
  if (model.includes('haiku') || model.includes('flash')) return 'Flash'
  if (model.includes('sonnet')) return 'Sonnet'
  if (model.includes('opus')) return 'Opus'
  if (model.includes('pro')) return 'Pro'
  return model.split('-').pop() || model
}

// ============================================================================
// Cost formatting
// ============================================================================

function formatCost(cost?: number): string | null {
  if (cost === undefined || cost === null) return null
  if (cost < 0.01) return '<$0.01'
  return `$${cost.toFixed(2)}`
}

// ============================================================================
// Extract model from progress log
// ============================================================================

function extractModelFromLog(progressLog?: string | null): string | undefined {
  if (!progressLog) return undefined
  const modelPatterns = [
    /with\s+(claude-[a-z0-9-]+)/i,
    /with\s+(gemini-[a-z0-9-]+)/i,
    /model[:\s]+([a-z]+-[a-z0-9-]+)/i,
    /(claude-sonnet|claude-opus|claude-haiku|gemini-flash|gemini-pro)/i,
  ]
  for (const pattern of modelPatterns) {
    const match = progressLog.match(pattern)
    if (match?.[1]) return match[1]
  }
  return undefined
}

// ============================================================================
// Execution Badges Component
// ============================================================================

export function ExecutionBadges({
  task,
  compact = false,
  className = '',
}: ExecutionBadgesProps) {
  const statusConfig = statusIcons[task.status] || statusIcons.pending

  const metadata: ExecutionMetadata = {
    model: extractModelFromLog(task.progress_log),
    retryCount: task.total_sessions > 1 ? task.total_sessions : undefined,
    cost: task.total_tokens_used ? task.total_tokens_used * 0.00001 : undefined,
  }

  const modelName = formatModelName(metadata.model)
  const costDisplay = formatCost(metadata.cost)

  if (compact) {
    return (
      <div
        className={clsx('inline-flex items-center gap-1', className)}
        title={task.status}
      >
        <span
          className={clsx('p-1 rounded', statusConfig.bg, statusConfig.color)}
        >
          {statusConfig.icon}
        </span>
      </div>
    )
  }

  return (
    <div className={clsx('inline-flex items-center gap-2', className)}>
      {/* Status badge */}
      <span
        className={clsx('inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs', statusConfig.bg, statusConfig.color, 'border border-current/20')}
        title={`Status: ${task.status}`}
      >
        {statusConfig.icon}
        <span className="capitalize">{task.status.replace('_', ' ')}</span>
      </span>

      {/* Model badge */}
      {modelName && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400 border border-purple-500/20"
          title={`Model: ${metadata.model}`}
        >
          <Zap className="h-3 w-3" />
          {modelName}
        </span>
      )}

      {/* Retry count */}
      {metadata.retryCount && metadata.retryCount > 1 && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-amber-500/20 text-amber-400 border border-amber-500/20"
          title={`Retry count: ${metadata.retryCount}`}
        >
          <RefreshCw className="h-3 w-3" />
          {metadata.retryCount}
        </span>
      )}

      {/* Cost badge */}
      {costDisplay && (
        <span
          className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-xs bg-slate-500/20 text-slate-400 border border-slate-500/20"
          title={`Estimated cost: ${costDisplay}`}
        >
          <DollarSign className="h-3 w-3" />
          {costDisplay}
        </span>
      )}
    </div>
  )
}

// ============================================================================
// Simple Status Icon (for inline use)
// ============================================================================

interface StatusIconProps {
  status: TaskStatus
  className?: string
}

export function StatusIcon({ status, className = '' }: StatusIconProps) {
  const config = statusIcons[status] || statusIcons.pending
  return (
    <span className={clsx(config.color, className)} title={status}>
      {config.icon}
    </span>
  )
}
