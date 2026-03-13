import {
  AlertCircle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Loader2,
  MessageSquare,
  Terminal,
  XCircle,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import type { EventVisibility } from '@/lib/api/events'
import { formatTimestamp } from '@/lib/format'

export interface TimelineMessage {
  type:
    | 'log'
    | 'progress'
    | 'model_change'
    | 'chat_message'
    | 'error'
    | 'connected'
  task_id: string
  data: Record<string, unknown>
  timestamp: string
  sequence: number
  event_id?: string
  trace_id?: string
  span_id?: string | null
  visibility?: EventVisibility
}


export function TimelineEvent({ message }: { message: TimelineMessage }) {
  const [expanded, setExpanded] = useState(false)
  const { time, isRecent } = formatTimestamp(message.timestamp)

  const handleKeyToggle = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault()
      setExpanded(!expanded)
    }
  }

  // Log message
  if (message.type === 'log') {
    const level = message.data.level as string
    const text = message.data.message as string
    const source = message.data.source as string
    const isToolCall = text?.toLowerCase().includes('tool') || source === 'tool'
    const details = message.data.details as Record<string, unknown> | undefined
    const attributes = message.data.attributes as Record<string, unknown> | undefined
    const hasDetails = Boolean(details || attributes)

    const levelConfig: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
      debug: { color: 'text-slate-500', bg: 'bg-slate-800/20', icon: null },
      info: { color: 'text-cyan-400', bg: 'bg-slate-800/30', icon: null },
      warning: { color: 'text-amber-400', bg: 'bg-amber-950/20', icon: <AlertCircle className="h-3 w-3 text-amber-400" /> },
      error: { color: 'text-red-400', bg: 'bg-red-950/20', icon: <XCircle className="h-3 w-3 text-red-400" /> },
    }
    const config = levelConfig[level] || levelConfig.info

    return (
      <div
        role={hasDetails ? 'button' : undefined}
        tabIndex={hasDetails ? 0 : undefined}
        className={`group flex gap-3 py-2 px-3 ${config.bg} hover:bg-slate-700/30 transition-colors border-b border-slate-800/30 ${hasDetails ? 'cursor-pointer' : ''}`}
        onClick={() => hasDetails && setExpanded(!expanded)}
        onKeyDown={hasDetails ? handleKeyToggle : undefined}
      >
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <div className="flex items-center gap-2 shrink-0 w-14">
          {config.icon || (isToolCall ? <Terminal className="h-3 w-3 text-violet-400" /> : null)}
          <span className={`text-2xs mono font-medium ${config.color}`}>
            {level.toUpperCase().slice(0, 4)}
          </span>
        </div>
        <div className="flex-1 min-w-0">
          <span className="text-sm text-slate-300 break-words leading-relaxed">{text}</span>
          {expanded && hasDetails && (
            <pre className="mt-2 text-xs text-slate-500 bg-slate-900/50 rounded p-2 overflow-x-auto">
              {JSON.stringify(details || attributes, null, 2)}
            </pre>
          )}
        </div>
        {source && source !== 'orchestrator' && (
          <span className="text-2xs text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
            {source}
          </span>
        )}
        {hasDetails && (
          <span className="text-slate-600 shrink-0">
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </span>
        )}
      </div>
    )
  }

  // Progress update
  if (message.type === 'progress') {
    const subtaskId = message.data.subtask_id as string | null
    const step = message.data.step as number | null
    const status = message.data.status as string
    const completed = message.data.completed_subtasks as number | null
    const total = message.data.total_subtasks as number | null
    const description = message.data.description as string | null

    const statusConfig: Record<string, { icon: React.ReactNode; color: string; bg: string; border: string }> = {
      in_progress: {
        icon: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-400" />,
        color: 'text-blue-400',
        bg: 'bg-blue-950/30',
        border: 'border-l-blue-500',
      },
      completed: {
        icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />,
        color: 'text-emerald-400',
        bg: 'bg-emerald-950/20',
        border: 'border-l-emerald-500',
      },
      passed: {
        icon: <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />,
        color: 'text-emerald-400',
        bg: 'bg-emerald-950/20',
        border: 'border-l-emerald-500',
      },
      failed: {
        icon: <XCircle className="h-3.5 w-3.5 text-red-400" />,
        color: 'text-red-400',
        bg: 'bg-red-950/20',
        border: 'border-l-red-500',
      },
    }
    const config = statusConfig[status] || statusConfig.in_progress

    return (
      <div className={`flex items-center gap-3 py-2.5 px-3 ${config.bg} border-l-2 ${config.border} border-b border-slate-800/30`}>
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <div className="flex items-center gap-2 shrink-0">
          {config.icon}
        </div>
        <div className="flex-1 flex items-center gap-2 flex-wrap">
          {subtaskId && (
            <span className="inline-flex items-center gap-1.5">
              <span className="text-xs font-medium text-slate-500 uppercase tracking-wide">Subtask</span>
              <span className={`mono text-sm font-semibold ${config.color}`}>{subtaskId}</span>
            </span>
          )}
          {step !== null && (
            <span className="inline-flex items-center gap-1.5 px-2 py-0.5 bg-slate-800/50 rounded-full">
              <span className="text-xs text-slate-500">Step</span>
              <span className="mono text-xs font-medium text-slate-300">{step}</span>
            </span>
          )}
          {description && (
            <span className="text-sm text-slate-400 truncate max-w-[300px]" title={description}>
              {description}
            </span>
          )}
          {completed !== null && total !== null && (
            <span className="ml-auto text-xs px-2 py-0.5 bg-slate-800/50 rounded-full text-slate-400 tabular-nums">
              {completed}/{total}
            </span>
          )}
        </div>
      </div>
    )
  }

  // Model change
  if (message.type === 'model_change') {
    const model = message.data.model as string
    const reason = message.data.reason as string

    return (
      <div className="flex items-center gap-3 py-2.5 px-3 bg-violet-950/30 border-l-2 border-violet-500 border-b border-slate-800/30">
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <Zap className="h-3.5 w-3.5 text-violet-400" />
        <div className="flex-1 flex items-center gap-2">
          <span className="text-xs font-medium text-violet-400 uppercase tracking-wide">Model</span>
          <span className="text-sm font-semibold text-violet-300">{model}</span>
          {reason && (
            <span className="text-xs text-violet-400/60">— {reason}</span>
          )}
        </div>
      </div>
    )
  }

  // Chat message
  if (message.type === 'chat_message') {
    const text = message.data.message as string
    const sender = message.data.sender as string | undefined
    const isUser = sender === 'user' || !sender

    return (
      <div className={`flex gap-3 py-3 px-3 border-l-2 border-b border-slate-800/30 ${isUser ? 'bg-slate-800/30 border-l-slate-500' : 'bg-cyan-950/20 border-l-cyan-500'}`}>
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <MessageSquare className={`h-3.5 w-3.5 mt-0.5 shrink-0 ${isUser ? 'text-slate-400' : 'text-cyan-400'}`} />
        <div className="flex-1 min-w-0">
          <span className={`text-xs font-semibold uppercase tracking-wide ${isUser ? 'text-slate-400' : 'text-cyan-400'}`}>
            {isUser ? 'You' : 'Agent'}
          </span>
          <p className="text-sm text-slate-300 mt-1 leading-relaxed whitespace-pre-wrap">{text}</p>
        </div>
      </div>
    )
  }

  // Error
  if (message.type === 'error') {
    const error = message.data.error as string
    const recoverable = message.data.recoverable as boolean
    const details = message.data.details as string | undefined

    return (
      <div
        role={details ? 'button' : undefined}
        tabIndex={details ? 0 : undefined}
        className={`flex gap-3 py-2.5 px-3 bg-red-950/30 border-l-2 border-red-500 border-b border-slate-800/30 ${details ? 'cursor-pointer' : ''}`}
        onClick={() => details && setExpanded(!expanded)}
        onKeyDown={details ? handleKeyToggle : undefined}
      >
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <AlertCircle className="h-3.5 w-3.5 text-red-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-red-300 break-words">{error}</span>
            {!recoverable && (
              <span className="text-2xs px-1.5 py-0.5 bg-red-500/30 text-red-400 rounded font-semibold uppercase tracking-wide">
                Fatal
              </span>
            )}
            {recoverable && (
              <span className="text-2xs px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded font-medium">
                Recoverable
              </span>
            )}
          </div>
          {expanded && details && (
            <pre className="mt-2 text-xs text-red-400/70 bg-red-950/30 rounded p-2 overflow-x-auto">
              {details}
            </pre>
          )}
        </div>
        {details && (
          <span className="text-slate-600 shrink-0">
            {expanded ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
          </span>
        )}
      </div>
    )
  }

  // Connected
  if (message.type === 'connected') {
    return (
      <div className="flex items-center gap-3 py-1.5 px-3 bg-slate-900/50 border-b border-slate-800/30">
        <span className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}>
          {time}
        </span>
        <div className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse" />
        <span className="text-xs text-slate-500">Connected to execution stream</span>
      </div>
    )
  }

  return null
}
