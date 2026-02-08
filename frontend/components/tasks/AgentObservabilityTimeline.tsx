'use client'

import { AlertCircle, Loader2, Radio, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AgentEventType, AgentHubEvent } from '@/lib/api/tasks'
import { AgentTimelineEvent } from './AgentTimelineEvent'
import { useAgentHubEvents } from './hooks/useAgentHubEvents'
import { TimelineFilters } from './TimelineFilters'
import { TurnGroup } from './TurnGroup'

interface AgentObservabilityTimelineProps {
  taskId: string
  projectId?: string
  isLive?: boolean
  pollInterval?: number
  maxHeight?: string
  className?: string
  groupByTurn?: boolean
}

export function AgentObservabilityTimeline({
  taskId,
  projectId,
  isLive = false,
  pollInterval = 5000,
  maxHeight = '500px',
  className = '',
  groupByTurn = true,
}: AgentObservabilityTimelineProps) {
  const [activeFilter, setActiveFilter] = useState<string>('all')
  const [filterEventTypes, setFilterEventTypes] = useState<AgentEventType[] | undefined>(undefined)
  const [searchTerm, setSearchTerm] = useState('')
  const scrollRef = useRef<HTMLDivElement>(null)
  const wasAtBottomRef = useRef(true)

  const { events, sessionIds, total, maxTurn, isLoading, error, refetch } =
    useAgentHubEvents({
      taskId,
      projectId,
      enabled: !!projectId,
      pollInterval: isLive ? pollInterval : 0,
    })

  const checkIfAtBottom = useCallback(() => {
    if (!scrollRef.current) return true
    const { scrollTop, scrollHeight, clientHeight } = scrollRef.current
    return scrollHeight - scrollTop - clientHeight < 50
  }, [])

  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    }
  }, [])

  useEffect(() => {
    if (wasAtBottomRef.current && events.length > 0) {
      scrollToBottom()
    }
  }, [events, scrollToBottom])

  const handleScroll = useCallback(() => {
    wasAtBottomRef.current = checkIfAtBottom()
  }, [checkIfAtBottom])

  const handleFilterChange = useCallback(
    (filterId: string, eventTypes: AgentEventType[] | undefined) => {
      setActiveFilter(filterId)
      setFilterEventTypes(eventTypes)
    },
    [],
  )

  const filteredEvents = useMemo(() => {
    let filtered = events

    if (filterEventTypes && filterEventTypes.length > 0) {
      filtered = filtered.filter((e) => filterEventTypes.includes(e.event_type))
    }

    if (searchTerm) {
      const term = searchTerm.toLowerCase()
      filtered = filtered.filter(
        (e) =>
          e.content?.toLowerCase().includes(term) ||
          e.tool_name?.toLowerCase().includes(term) ||
          JSON.stringify(e.tool_input)?.toLowerCase().includes(term) ||
          JSON.stringify(e.tool_output)?.toLowerCase().includes(term),
      )
    }

    return filtered
  }, [events, filterEventTypes, searchTerm])

  const eventCounts = useMemo(() => {
    const counts: Record<string, number> = {}
    for (const event of events) {
      counts[event.event_type] = (counts[event.event_type] || 0) + 1
    }
    return counts
  }, [events])

  const eventsByTurn = useMemo(() => {
    const grouped = new Map<string, { sessionIndex: number; turn: number; events: AgentHubEvent[] }>()
    for (const event of filteredEvents) {
      const key = `${event.session_index ?? 0}-${event.turn}`
      const group = grouped.get(key)
      if (group) {
        group.events.push(event)
      } else {
        grouped.set(key, { sessionIndex: event.session_index ?? 0, turn: event.turn, events: [event] })
      }
    }
    return Array.from(grouped.values())
      .sort((a, b) => a.sessionIndex - b.sessionIndex || a.turn - b.turn)
      .map(({ turn, events: turnEvents }) => ({
        turn,
        events: turnEvents.sort((a, b) => a.sequence - b.sequence),
      }))
  }, [filteredEvents])

  const heightStyle =
    maxHeight === 'none' ? { minHeight: '200px' } : { minHeight: '200px', maxHeight }

  return (
    <div className={`flex flex-col ${className}`}>
      <div className="flex items-center justify-between px-3 py-2.5 bg-slate-900/60 border border-slate-800/50 rounded-t-lg">
        <div className="flex items-center gap-2">
          <Radio className="h-3.5 w-3.5 text-slate-500" />
          <h3 className="text-xs font-semibold text-slate-400 uppercase tracking-wide">
            Agent Observability
          </h3>
          {sessionIds.length > 0 && (
            <span className="text-2xs px-1.5 py-0.5 bg-slate-800 text-slate-500 rounded">
              {sessionIds.length} session{sessionIds.length !== 1 ? 's' : ''}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          {isLive && (
            <span className="flex items-center gap-1.5 text-xs text-emerald-400 font-medium">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
              </span>
              Live
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isLoading}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded bg-slate-800/50 hover:bg-slate-700/50 transition-colors disabled:opacity-50"
          >
            <RefreshCw className={`h-3 w-3 ${isLoading ? 'animate-spin' : ''}`} />
            Refresh
          </button>
        </div>
      </div>

      <TimelineFilters
        activeFilter={activeFilter}
        searchTerm={searchTerm}
        onFilterChange={handleFilterChange}
        onSearchChange={setSearchTerm}
        eventCounts={eventCounts}
      />

      <div
        ref={scrollRef}
        onScroll={handleScroll}
        className="flex-1 overflow-y-auto bg-slate-950/40 rounded-b-lg border border-slate-800/50 border-t-0"
        style={heightStyle}
      >
        {isLoading && events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            <Loader2 className="h-5 w-5 animate-spin mb-2" />
            <span className="text-sm">Loading agent events...</span>
          </div>
        ) : error && events.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            <AlertCircle className="h-5 w-5 mb-2 text-amber-500" />
            <span className="text-sm text-amber-500">{error}</span>
          </div>
        ) : filteredEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            {searchTerm || filterEventTypes ? (
              <span className="text-sm">No events match your filters</span>
            ) : sessionIds.length === 0 ? (
              <span className="text-sm">No Agent Hub sessions linked to this task</span>
            ) : (
              <span className="text-sm">No events recorded yet</span>
            )}
          </div>
        ) : groupByTurn ? (
          <div>
            {eventsByTurn.map(({ turn, events: turnEvents }) => (
              <TurnGroup
                key={turn}
                turn={turn}
                events={turnEvents}
                searchTerm={searchTerm}
                defaultExpanded={turn >= maxTurn - 2}
              />
            ))}
          </div>
        ) : (
          <div className="py-2">
            {filteredEvents.map((event) => (
              <AgentTimelineEvent
                key={event.id}
                event={event}
                searchTerm={searchTerm}
              />
            ))}
          </div>
        )}
      </div>

      {total > 0 && (
        <div className="flex items-center justify-between px-3 py-1.5 bg-slate-900/40 border border-slate-800/50 border-t-0 rounded-b-lg text-2xs text-slate-500">
          <span>
            {filteredEvents.length} of {total} events
            {searchTerm && ` matching "${searchTerm}"`}
          </span>
          <span>{maxTurn} turns</span>
        </div>
      )}
    </div>
  )
}
