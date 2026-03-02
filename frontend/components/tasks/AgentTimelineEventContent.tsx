'use client'

import { Clock } from 'lucide-react'
import type { AgentHubEvent } from '@/lib/api/tasks'
import { formatDuration } from '@/lib/format'
import type { EventConfig } from './agentTimelineConfig'
import { highlightText, formatTokens } from './agentTimelineUtils'

interface AgentTimelineEventContentProps {
  event: AgentHubEvent
  config: EventConfig
  expanded: boolean
  searchTerm?: string
}

export function AgentTimelineEventContent({
  event,
  config,
  expanded,
  searchTerm,
}: AgentTimelineEventContentProps) {
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
