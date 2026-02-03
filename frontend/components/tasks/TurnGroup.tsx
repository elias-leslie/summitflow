'use client'

import { ChevronDown, ChevronRight, Hash } from 'lucide-react'
import { useState } from 'react'
import type { AgentHubEvent } from '@/lib/api/tasks'
import { AgentTimelineEvent } from './AgentTimelineEvent'

interface TurnGroupProps {
  turn: number
  events: AgentHubEvent[]
  searchTerm?: string
  defaultExpanded?: boolean
}

export function TurnGroup({
  turn,
  events,
  searchTerm,
  defaultExpanded = true,
}: TurnGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded)

  const thinkingEvent = events.find((e) => e.event_type === 'thinking')
  const toolEvents = events.filter(
    (e) => e.event_type === 'tool_use' || e.event_type === 'tool_result',
  )
  const messageEvents = events.filter(
    (e) =>
      e.event_type === 'user_message' ||
      e.event_type === 'assistant_message' ||
      e.event_type === 'system_message',
  )
  const errorEvents = events.filter((e) => e.event_type === 'error')

  const totalTokens = events.reduce((acc, e) => acc + (e.tokens || 0), 0)
  const totalDuration = events.reduce((acc, e) => acc + (e.duration_ms || 0), 0)

  return (
    <div className="border-b border-slate-700/50">
      <button
        onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center gap-2 px-3 py-2 bg-slate-900/60 hover:bg-slate-800/60 transition-colors sticky top-0 z-10"
      >
        {expanded ? (
          <ChevronDown className="h-3.5 w-3.5 text-slate-500" />
        ) : (
          <ChevronRight className="h-3.5 w-3.5 text-slate-500" />
        )}

        <div className="flex items-center gap-1.5">
          <Hash className="h-3 w-3 text-slate-600" />
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
            Turn {turn}
          </span>
        </div>

        <div className="flex items-center gap-2 ml-auto">
          {messageEvents.length > 0 && (
            <span className="text-2xs px-1.5 py-0.5 bg-cyan-500/15 text-cyan-400 rounded">
              {messageEvents.length} msg
            </span>
          )}
          {thinkingEvent && (
            <span className="text-2xs px-1.5 py-0.5 bg-amber-500/15 text-amber-400 rounded">
              think
            </span>
          )}
          {toolEvents.length > 0 && (
            <span className="text-2xs px-1.5 py-0.5 bg-emerald-500/15 text-emerald-400 rounded">
              {toolEvents.filter((e) => e.event_type === 'tool_use').length} tools
            </span>
          )}
          {errorEvents.length > 0 && (
            <span className="text-2xs px-1.5 py-0.5 bg-red-500/15 text-red-400 rounded">
              {errorEvents.length} err
            </span>
          )}
          {totalTokens > 0 && (
            <span className="text-2xs text-slate-500 tabular-nums">
              {totalTokens > 1000 ? `${(totalTokens / 1000).toFixed(1)}k` : totalTokens} tok
            </span>
          )}
          {totalDuration > 0 && (
            <span className="text-2xs text-slate-600 tabular-nums">
              {totalDuration > 1000 ? `${(totalDuration / 1000).toFixed(1)}s` : `${totalDuration}ms`}
            </span>
          )}
        </div>
      </button>

      {expanded && (
        <div>
          {events.map((event) => (
            <AgentTimelineEvent
              key={event.id}
              event={event}
              searchTerm={searchTerm}
            />
          ))}
        </div>
      )}
    </div>
  )
}
