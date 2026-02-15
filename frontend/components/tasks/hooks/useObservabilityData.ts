import { useMemo } from 'react'
import type { AgentEventType, AgentHubEvent } from '@/lib/api/tasks'

interface UseObservabilityDataParams {
  events: AgentHubEvent[]
  filterEventTypes: AgentEventType[] | undefined
  searchTerm: string
}

export function useObservabilityData({
  events,
  filterEventTypes,
  searchTerm,
}: UseObservabilityDataParams) {
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

  return { filteredEvents, eventCounts, eventsByTurn, replayTimestamps }
}
