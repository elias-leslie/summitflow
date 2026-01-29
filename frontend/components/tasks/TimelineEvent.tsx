import {
  AlertCircle,
  CheckCircle2,
  Loader2,
  MessageSquare,
  XCircle,
  Zap,
} from 'lucide-react'
import type { EventVisibility } from '@/lib/api/events'

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
  trace_id?: string
  span_id?: string | null
  visibility?: EventVisibility
}

export function TimelineEvent({ message }: { message: TimelineMessage }) {
  const time = new Date(message.timestamp).toLocaleTimeString('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })

  // Log message
  if (message.type === 'log') {
    const level = message.data.level as string
    const text = message.data.message as string
    const source = message.data.source as string

    const levelColors: Record<string, string> = {
      debug: 'text-slate-500',
      info: 'text-slate-400',
      warning: 'text-amber-400',
      error: 'text-red-400',
    }

    return (
      <div className="flex gap-3 py-1.5 px-3 hover:bg-slate-800/30">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <span
          className={`text-2xs mono shrink-0 w-12 ${levelColors[level] || 'text-slate-400'}`}
        >
          {level.toUpperCase()}
        </span>
        <span className="text-sm text-slate-300 break-words">{text}</span>
        {source && source !== 'orchestrator' && (
          <span className="text-2xs text-slate-600 ml-auto shrink-0">
            [{source}]
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

    const statusIcons: Record<string, React.ReactNode> = {
      in_progress: <Loader2 className="h-3 w-3 animate-spin text-blue-400" />,
      completed: <CheckCircle2 className="h-3 w-3 text-phosphor-400" />,
      failed: <XCircle className="h-3 w-3 text-red-400" />,
    }

    return (
      <div className="flex items-center gap-3 py-1.5 px-3 bg-slate-800/20">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        {statusIcons[status] || <div className="w-3" />}
        <span className="text-sm text-slate-300">
          {subtaskId && (
            <>
              <span className="text-slate-500">Subtask</span>{' '}
              <span className="mono text-phosphor-400">{subtaskId}</span>
              {step !== null && (
                <>
                  {' '}
                  <span className="text-slate-500">step</span>{' '}
                  <span className="mono">{step}</span>
                </>
              )}
            </>
          )}
          {completed !== null && total !== null && (
            <span className="text-slate-500 ml-2">
              ({completed}/{total} subtasks)
            </span>
          )}
        </span>
      </div>
    )
  }

  // Model change
  if (message.type === 'model_change') {
    const model = message.data.model as string
    const reason = message.data.reason as string

    return (
      <div className="flex items-center gap-3 py-1.5 px-3 bg-purple-950/20 border-l-2 border-purple-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <Zap className="h-3 w-3 text-purple-400" />
        <span className="text-sm text-purple-300">
          Switched to <span className="font-medium">{model}</span>
          {reason && (
            <span className="text-purple-400/70 ml-1">— {reason}</span>
          )}
        </span>
      </div>
    )
  }

  // Chat message
  if (message.type === 'chat_message') {
    const text = message.data.message as string
    const sender = message.data.sender as string | undefined
    const isUser = sender === 'user' || !sender

    return (
      <div className="flex gap-3 py-2 px-3 bg-blue-950/20 border-l-2 border-blue-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <MessageSquare className="h-3 w-3 text-blue-400 mt-0.5" />
        <div className="flex-1">
          <span className="text-xs font-medium text-blue-400">
            {isUser ? 'You:' : 'Agent:'}
          </span>
          <p className="text-sm text-slate-300 mt-0.5">{text}</p>
        </div>
      </div>
    )
  }

  // Error
  if (message.type === 'error') {
    const error = message.data.error as string
    const recoverable = message.data.recoverable as boolean

    return (
      <div className="flex items-center gap-3 py-2 px-3 bg-red-950/20 border-l-2 border-red-500">
        <span className="text-2xs text-slate-600 mono shrink-0 w-16">
          {time}
        </span>
        <AlertCircle className="h-3 w-3 text-red-400" />
        <span className="text-sm text-red-300">{error}</span>
        {!recoverable && (
          <span className="text-2xs px-1.5 py-0.5 bg-red-500/20 text-red-400 rounded">
            Fatal
          </span>
        )}
      </div>
    )
  }

  // Connected
  if (message.type === 'connected') {
    return (
      <div className="flex items-center gap-3 py-1 px-3 text-xs text-slate-600">
        <span className="mono shrink-0 w-16">{time}</span>
        <span>Connected to execution stream</span>
      </div>
    )
  }

  return null
}
