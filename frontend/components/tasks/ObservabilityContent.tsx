'use client'

import { AlertCircle, Loader2 } from 'lucide-react'
import type { RefObject } from 'react'
import type { AgentHubEvent, AgentHubSessionSummary } from '@/lib/api/tasks'
import { AgentTimelineEvent } from './AgentTimelineEvent'
import { SpanTree } from './SpanTree'
import { TurnGroup } from './TurnGroup'

type ViewMode = 'timeline' | 'spans' | 'replay'

interface EventsByTurn {
  turn: number
  events: AgentHubEvent[]
}

interface ObservabilityContentProps {
  viewMode: ViewMode
  projectId?: string
  taskId: string
  isLoading: boolean
  error: string | null
  events: AgentHubEvent[]
  filteredEvents: AgentHubEvent[]
  eventsByTurn: EventsByTurn[]
  sessionIds: string[]
  sessions: AgentHubSessionSummary[]
  searchTerm: string
  filterEventTypes: string[] | undefined
  groupByTurn: boolean
  replayIndex: number
  maxTurn: number
  heightStyle: { minHeight: string; maxHeight?: string }
  scrollRef: RefObject<HTMLDivElement | null>
  onScroll: () => void
}

export function ObservabilityContent({
  viewMode,
  projectId,
  taskId,
  isLoading,
  error,
  events,
  filteredEvents,
  eventsByTurn,
  sessionIds,
  sessions,
  searchTerm,
  filterEventTypes,
  groupByTurn,
  replayIndex,
  maxTurn,
  heightStyle,
  scrollRef,
  onScroll,
}: ObservabilityContentProps) {
  if (viewMode === 'spans' && projectId) {
    return (
      <div
        className="flex-1 overflow-y-auto bg-slate-950/40 rounded-b-lg border border-slate-800/50 border-t-0"
        style={heightStyle}
      >
        <SpanTree
          projectId={projectId}
          traceId={taskId}
        />
      </div>
    )
  }

  return (
    <div
      ref={scrollRef}
      onScroll={onScroll}
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
            <div className="text-center space-y-2">
              <span className="text-sm block">No events recorded yet</span>
              {sessions.length > 0 && (
                <div className="text-xs text-slate-500 font-mono">
                  {sessions.map((session) => {
                    const live = session.live_activity
                    return (
                      <div key={session.id}>
                        {(session.effective_model || session.requested_model || session.id).split('/').pop()} · {live ? `${live.health}/${live.phase}` : session.status}
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
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
  )
}
