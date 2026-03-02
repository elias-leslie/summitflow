'use client'

import { ChevronDown, ChevronRight } from 'lucide-react'
import { useState } from 'react'
import type { AgentHubEvent } from '@/lib/api/tasks'
import { formatTimestamp } from '@/lib/format'
import { EVENT_CONFIG } from './agentTimelineConfig'
import { AgentTimelineEventContent } from './AgentTimelineEventContent'

interface AgentTimelineEventProps {
  event: AgentHubEvent
  searchTerm?: string
}

export function AgentTimelineEvent({ event, searchTerm }: AgentTimelineEventProps) {
  const [expanded, setExpanded] = useState(false)
  const { time, isRecent } = formatTimestamp(event.created_at)
  const config = EVENT_CONFIG[event.event_type] || EVENT_CONFIG.error

  const hasExpandableContent =
    event.tool_input ||
    event.tool_output ||
    (event.content && event.content.length > 200)

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

      <AgentTimelineEventContent
        event={event}
        config={config}
        expanded={expanded}
        searchTerm={searchTerm}
      />

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
