'use client'

import clsx from 'clsx'
import { useCallback, useState } from 'react'
import type { AgentEventType } from '@/lib/api/tasks'
import { useAgentHubEvents } from './hooks/useAgentHubEvents'
import { useAutoScroll } from './hooks/useAutoScroll'
import { useObservabilityData } from './hooks/useObservabilityData'
import { ObservabilityContent } from './ObservabilityContent'
import { ObservabilityFooter } from './ObservabilityFooter'
import { ObservabilityHeader } from './ObservabilityHeader'
import { ReplayControls } from './ReplayControls'
import { TimelineFilters } from './TimelineFilters'

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

  const { events, sessionIds, sessions, total, maxTurn, isLoading, error, refetch } =
    useAgentHubEvents({
      taskId,
      projectId,
      enabled: !!projectId,
      pollInterval: isLive ? pollInterval : 0,
    })

  const { scrollRef, handleScroll } = useAutoScroll(events.length)

  const { filteredEvents, eventCounts, eventsByTurn, replayTimestamps } = useObservabilityData({
    events,
    filterEventTypes,
    searchTerm,
  })

  const handleFilterChange = useCallback(
    (filterId: string, eventTypes: AgentEventType[] | undefined) => {
      setActiveFilter(filterId)
      setFilterEventTypes(eventTypes)
    },
    [],
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
    <div className={clsx('flex flex-col', className)}>
      <ObservabilityHeader
        viewMode={viewMode}
        sessionIds={sessionIds}
        sessions={sessions}
        isLive={isLive}
        isLoading={isLoading}
        onViewModeChange={setViewMode}
        onRefresh={refetch}
      />

      {viewMode !== 'spans' && (
        <TimelineFilters
          activeFilter={activeFilter}
          searchTerm={searchTerm}
          onFilterChange={handleFilterChange}
          onSearchChange={setSearchTerm}
          eventCounts={eventCounts}
        />
      )}

      <ObservabilityContent
        viewMode={viewMode}
        projectId={projectId}
        taskId={taskId}
        isLoading={isLoading}
        error={error}
        events={events}
        filteredEvents={filteredEvents}
        eventsByTurn={eventsByTurn}
        sessionIds={sessionIds}
        sessions={sessions}
        searchTerm={searchTerm}
        filterEventTypes={filterEventTypes}
        groupByTurn={groupByTurn}
        replayIndex={replayIndex}
        maxTurn={maxTurn}
        heightStyle={heightStyle}
        scrollRef={scrollRef}
        onScroll={handleScroll}
      />

      {viewMode === 'replay' && filteredEvents.length > 0 && (
        <ReplayControls
          totalEvents={filteredEvents.length}
          currentIndex={replayIndex}
          onIndexChange={handleReplayIndexChange}
          timestamps={replayTimestamps}
          className="border-t-0 rounded-t-none rounded-b-lg"
        />
      )}

      {total > 0 && viewMode !== 'replay' && viewMode !== 'spans' && (
        <ObservabilityFooter
          filteredCount={filteredEvents.length}
          totalCount={total}
          maxTurn={maxTurn}
          searchTerm={searchTerm}
        />
      )}
    </div>
  )
}
