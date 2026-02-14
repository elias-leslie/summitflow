'use client'

import { AlertCircle, GitBranch, List, Loader2, Play, Radio, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { AgentEventType, AgentHubEvent } from '@/lib/api/tasks'
import { AgentTimelineEvent } from './AgentTimelineEvent'
import { useAgentHubEvents } from './hooks/useAgentHubEvents'
import { ReplayControls } from './ReplayControls'
import { SpanTree } from './SpanTree'
import { TimelineFilters } from './TimelineFilters'
import { TurnGroup } from './TurnGroup'

type ViewMode = 'timeline' | 'spans' | 'replay'

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
  const [viewMode, setViewMode] = useState<ViewMode>('timeline')
  const [activeFilter, setActiveFilter] = useState<string>('all')
  const [filterEventTypes, setFilterEventTypes] = useState<AgentEventType[] | undefined>(undefined)
  const [searchTerm, setSearchTerm] = useState('')
  const [replayIndex, setReplayIndex] = useState(0)
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

  const replayTimestamps = useMemo(
    () => filteredEvents.map((e) => e.created_at),
    [filteredEvents],
  )

  const handleReplayIndexChange = useCallback(
    (index: number) => {
      setReplayIndex(index)
      // Scroll the highlighted event into view
      if (scrollRef.current) {
        const eventElements = scrollRef.current.querySelectorAll('[data-event-index]')
        const target = eventElements[index]
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
        }
      }
    },
    [],
  )

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
          {/* View mode tabs */}
          <div className="flex items-center bg-slate-800/60 rounded-md p-0.5">
            {([
              { mode: 'timeline' as const, icon: List, label: 'Timeline' },
              { mode: 'spans' as const, icon: GitBranch, label: 'Spans' },
              { mode: 'replay' as const, icon: Play, label: 'Replay' },
            ]).map(({ mode, icon: Icon, label }) => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className={`flex items-center gap-1 px-2 py-1 rounded text-2xs font-medium transition-colors ${
                  viewMode === mode
                    ? 'bg-slate-700 text-slate-200'
                    : 'text-slate-500 hover:text-slate-400'
                }`}
                title={label}
              >
                <Icon className="h-3 w-3" />
                <span className="hidden sm:inline">{label}</span>
              </button>
            ))}
          </div>

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

      {viewMode !== 'spans' && (
        <TimelineFilters
          activeFilter={activeFilter}
          searchTerm={searchTerm}
          onFilterChange={handleFilterChange}
          onSearchChange={setSearchTerm}
          eventCounts={eventCounts}
        />
      )}

      {viewMode === 'spans' && projectId ? (
        <div
          className="flex-1 overflow-y-auto bg-slate-950/40 rounded-b-lg border border-slate-800/50 border-t-0"
          style={heightStyle}
        >
          <SpanTree
            projectId={projectId}
            traceId={taskId}
          />
        </div>
      ) : (
        <>
          <div
            ref={scrollRef}
            onScroll={handleScroll}
            className={`flex-1 overflow-y-auto bg-slate-950/40 border border-slate-800/50 border-t-0 ${viewMode === 'replay' ? '' : 'rounded-b-lg'}`}
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
            ) : viewMode === 'replay' ? (
              <div className="py-2">
                {filteredEvents.map((event, idx) => (
                  <div
                    key={event.id}
                    data-event-index={idx}
                    className={idx === replayIndex ? 'ring-1 ring-cyan-500/50 ring-inset' : idx > replayIndex ? 'opacity-30' : ''}
                  >
                    <AgentTimelineEvent
                      event={event}
                      searchTerm={searchTerm}
                    />
                  </div>
                ))}
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

          {viewMode === 'replay' && filteredEvents.length > 0 && (
            <ReplayControls
              totalEvents={filteredEvents.length}
              currentIndex={replayIndex}
              onIndexChange={handleReplayIndexChange}
              timestamps={replayTimestamps}
              className="border-t-0 rounded-t-none rounded-b-lg"
            />
          )}
        </>
      )}

      {total > 0 && viewMode !== 'replay' && viewMode !== 'spans' && (
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
