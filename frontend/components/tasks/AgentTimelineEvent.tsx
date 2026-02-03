'use client'

import {
  AlertCircle,
  Brain,
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  MessageSquare,
  Quote,
  Terminal,
  User,
  Zap,
} from 'lucide-react'
import { useState } from 'react'
import type { AgentEventType, AgentHubEvent } from '@/lib/api/tasks'

interface AgentTimelineEventProps {
  event: AgentHubEvent
  searchTerm?: string
}

function formatTimestamp(timestamp: string): { time: string; isRecent: boolean } {
  const date = new Date(timestamp)
  const now = new Date()
  const diffMs = now.getTime() - date.getTime()
  const diffMins = Math.floor(diffMs / 60000)

  if (diffMins < 1) {
    const diffSecs = Math.floor(diffMs / 1000)
    return { time: `${diffSecs}s ago`, isRecent: true }
  }
  if (diffMins < 60) {
    return { time: `${diffMins}m ago`, isRecent: true }
  }
  return {
    time: date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    }),
    isRecent: false,
  }
}

function highlightText(text: string, searchTerm?: string): React.ReactNode {
  if (!searchTerm || !text) return text
  const regex = new RegExp(`(${searchTerm.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi')
  const parts = text.split(regex)
  return parts.map((part, i) =>
    regex.test(part) ? (
      <mark key={i} className="bg-amber-500/40 text-amber-200 rounded px-0.5">
        {part}
      </mark>
    ) : (
      part
    ),
  )
}

function formatDuration(ms: number | null): string {
  if (!ms) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function formatTokens(tokens: number | null): string {
  if (!tokens) return ''
  if (tokens > 1000) return `${(tokens / 1000).toFixed(1)}k`
  return tokens.toString()
}

const EVENT_CONFIG: Record<
  AgentEventType,
  {
    icon: React.ReactNode
    label: string
    color: string
    bg: string
    border: string
  }
> = {
  user_message: {
    icon: <User className="h-3.5 w-3.5" />,
    label: 'USER',
    color: 'text-slate-400',
    bg: 'bg-slate-800/40',
    border: 'border-l-slate-500',
  },
  assistant_message: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    label: 'ASST',
    color: 'text-cyan-400',
    bg: 'bg-cyan-950/30',
    border: 'border-l-cyan-500',
  },
  system_message: {
    icon: <Zap className="h-3.5 w-3.5" />,
    label: 'SYS',
    color: 'text-violet-400',
    bg: 'bg-violet-950/20',
    border: 'border-l-violet-500',
  },
  thinking: {
    icon: <Brain className="h-3.5 w-3.5" />,
    label: 'THINK',
    color: 'text-amber-400',
    bg: 'bg-amber-950/20',
    border: 'border-l-amber-500',
  },
  tool_use: {
    icon: <Terminal className="h-3.5 w-3.5" />,
    label: 'TOOL',
    color: 'text-emerald-400',
    bg: 'bg-emerald-950/20',
    border: 'border-l-emerald-500',
  },
  tool_result: {
    icon: <Terminal className="h-3.5 w-3.5" />,
    label: 'RESULT',
    color: 'text-teal-400',
    bg: 'bg-teal-950/20',
    border: 'border-l-teal-500',
  },
  memory_inject: {
    icon: <Database className="h-3.5 w-3.5" />,
    label: 'MEM',
    color: 'text-pink-400',
    bg: 'bg-pink-950/20',
    border: 'border-l-pink-500',
  },
  memory_cite: {
    icon: <Quote className="h-3.5 w-3.5" />,
    label: 'CITE',
    color: 'text-rose-400',
    bg: 'bg-rose-950/20',
    border: 'border-l-rose-500',
  },
  error: {
    icon: <AlertCircle className="h-3.5 w-3.5" />,
    label: 'ERR',
    color: 'text-red-400',
    bg: 'bg-red-950/30',
    border: 'border-l-red-500',
  },
}

export function AgentTimelineEvent({ event, searchTerm }: AgentTimelineEventProps) {
  const [expanded, setExpanded] = useState(false)
  const { time, isRecent } = formatTimestamp(event.created_at)
  const config = EVENT_CONFIG[event.event_type] || EVENT_CONFIG.error

  const hasExpandableContent =
    event.tool_input ||
    event.tool_output ||
    (event.content && event.content.length > 200)

  const renderContent = () => {
    switch (event.event_type) {
      case 'thinking':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Thinking
              </span>
              {event.tokens && (
                <span className="text-2xs px-1.5 py-0.5 bg-amber-500/20 text-amber-400 rounded tabular-nums">
                  {formatTokens(event.tokens)} tokens
                </span>
              )}
              {event.duration_ms && (
                <span className="text-2xs px-1.5 py-0.5 bg-slate-700/50 text-slate-400 rounded tabular-nums flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />
                  {formatDuration(event.duration_ms)}
                </span>
              )}
            </div>
            {event.content && (
              <p
                className={`text-sm text-slate-300/80 mt-1.5 leading-relaxed whitespace-pre-wrap font-mono text-xs ${expanded ? '' : 'line-clamp-3'}`}
              >
                {highlightText(event.content, searchTerm)}
              </p>
            )}
          </div>
        )

      case 'tool_use':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Tool Call
              </span>
              {event.tool_name && (
                <span className="text-sm font-semibold text-emerald-300 font-mono">
                  {highlightText(event.tool_name, searchTerm)}
                </span>
              )}
              {event.duration_ms && (
                <span className="text-2xs px-1.5 py-0.5 bg-slate-700/50 text-slate-400 rounded tabular-nums flex items-center gap-1">
                  <Clock className="h-2.5 w-2.5" />
                  {formatDuration(event.duration_ms)}
                </span>
              )}
            </div>
            {expanded && event.tool_input && (
              <pre className="mt-2 text-xs text-slate-400 bg-slate-900/70 rounded p-2.5 overflow-x-auto border border-slate-800/50">
                {JSON.stringify(event.tool_input, null, 2)}
              </pre>
            )}
          </div>
        )

      case 'tool_result':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Tool Result
              </span>
              {event.tool_name && (
                <span className="text-sm text-teal-300 font-mono">
                  {event.tool_name}
                </span>
              )}
            </div>
            {expanded && event.tool_output && (
              <pre className="mt-2 text-xs text-slate-400 bg-slate-900/70 rounded p-2.5 overflow-x-auto border border-slate-800/50 max-h-64">
                {JSON.stringify(event.tool_output, null, 2)}
              </pre>
            )}
            {!expanded && event.tool_output && (
              <p className="text-sm text-slate-500 mt-1 truncate">
                {typeof event.tool_output === 'object'
                  ? `${JSON.stringify(event.tool_output).slice(0, 100)}...`
                  : String(event.tool_output)}
              </p>
            )}
          </div>
        )

      case 'memory_inject':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Memory Injected
              </span>
              {event.tokens && (
                <span className="text-2xs px-1.5 py-0.5 bg-pink-500/20 text-pink-400 rounded tabular-nums">
                  {formatTokens(event.tokens)} tokens
                </span>
              )}
            </div>
            {event.content && (
              <p
                className={`text-sm text-slate-300/80 mt-1.5 leading-relaxed ${expanded ? '' : 'line-clamp-2'}`}
              >
                {highlightText(event.content, searchTerm)}
              </p>
            )}
          </div>
        )

      case 'memory_cite':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Memory Cited
              </span>
            </div>
            {event.content && (
              <p className="text-sm text-rose-300/80 mt-1.5 leading-relaxed italic">
                {highlightText(event.content, searchTerm)}
              </p>
            )}
          </div>
        )

      case 'user_message':
      case 'assistant_message':
      case 'system_message':
        return (
          <div className="flex-1 min-w-0">
            <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
              {event.event_type === 'user_message'
                ? 'User'
                : event.event_type === 'assistant_message'
                  ? 'Assistant'
                  : 'System'}
            </span>
            {event.content && (
              <p className="text-sm text-slate-300 mt-1 leading-relaxed whitespace-pre-wrap">
                {highlightText(event.content, searchTerm)}
              </p>
            )}
          </div>
        )

      case 'error':
        return (
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <span className={`text-xs font-semibold uppercase tracking-wide ${config.color}`}>
                Error
              </span>
            </div>
            {event.content && (
              <p className="text-sm text-red-300 mt-1 break-words">
                {highlightText(event.content, searchTerm)}
              </p>
            )}
            {expanded && event.tool_output && (
              <pre className="mt-2 text-xs text-red-400/70 bg-red-950/30 rounded p-2.5 overflow-x-auto">
                {JSON.stringify(event.tool_output, null, 2)}
              </pre>
            )}
          </div>
        )

      default:
        return (
          <div className="flex-1 min-w-0">
            <span className="text-sm text-slate-400">
              {event.content || 'Unknown event'}
            </span>
          </div>
        )
    }
  }

  return (
    <div
      className={`group flex gap-3 py-2.5 px-3 ${config.bg} border-l-2 ${config.border} hover:bg-slate-700/30 transition-colors border-b border-slate-800/30 ${hasExpandableContent ? 'cursor-pointer' : ''}`}
      onClick={() => hasExpandableContent && setExpanded(!expanded)}
    >
      <span
        className={`text-2xs mono shrink-0 w-14 tabular-nums ${isRecent ? 'text-cyan-500' : 'text-slate-600'}`}
      >
        {time}
      </span>

      <div className="flex items-center gap-1 shrink-0 w-10">
        <span className={config.color}>{config.icon}</span>
      </div>

      {renderContent()}

      {event.agent_name && (
        <span className="text-2xs text-slate-600 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
          {event.agent_name}
        </span>
      )}

      {hasExpandableContent && (
        <span className="text-slate-600 shrink-0">
          {expanded ? (
            <ChevronDown className="h-3 w-3" />
          ) : (
            <ChevronRight className="h-3 w-3" />
          )}
        </span>
      )}
    </div>
  )
}
