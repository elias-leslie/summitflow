'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import {
  type AgentEventType,
  type AgentHubEvent,
  type AgentHubEventsResponse,
  type AgentHubSessionSummary,
  fetchTaskAgentEvents,
} from '@/lib/api/tasks'
import { getErrorMessage } from '@/lib/utils'

interface UseAgentHubEventsOptions {
  taskId: string
  projectId?: string
  eventTypes?: AgentEventType[]
  turn?: number
  enabled?: boolean
  pollInterval?: number
}

interface UseAgentHubEventsReturn {
  events: AgentHubEvent[]
  sessionIds: string[]
  sessions: AgentHubSessionSummary[]
  total: number
  maxTurn: number
  isLoading: boolean
  error: string | null
  refetch: () => Promise<void>
}

export function useAgentHubEvents({
  taskId,
  projectId,
  eventTypes,
  turn,
  enabled = true,
  pollInterval = 0,
}: UseAgentHubEventsOptions): UseAgentHubEventsReturn {
  const [data, setData] = useState<AgentHubEventsResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const mountedRef = useRef(true)

  const fetchEvents = useCallback(async () => {
    if (!projectId || !enabled) return

    setIsLoading(true)
    setError(null)

    try {
      const response = await fetchTaskAgentEvents(projectId, taskId, {
        event_type: eventTypes?.[0],
        turn,
        page_size: 500,
      })

      if (!mountedRef.current) return

      let filteredEvents = response.events

      if (eventTypes && eventTypes.length > 0) {
        filteredEvents = response.events.filter((e) =>
          eventTypes.includes(e.event_type),
        )
      }

      setData({
        ...response,
        events: filteredEvents,
      })
    } catch (err) {
      if (!mountedRef.current) return
      setError(getErrorMessage(err, 'Failed to fetch events'))
    } finally {
      if (mountedRef.current) {
        setIsLoading(false)
      }
    }
  }, [projectId, taskId, eventTypes, turn, enabled])

  useEffect(() => {
    mountedRef.current = true
    fetchEvents()

    if (pollInterval > 0) {
      const poll = () => {
        pollTimeoutRef.current = setTimeout(() => {
          fetchEvents().then(() => {
            if (mountedRef.current) poll()
          })
        }, pollInterval)
      }
      poll()
    }

    return () => {
      mountedRef.current = false
      if (pollTimeoutRef.current) {
        clearTimeout(pollTimeoutRef.current)
      }
    }
  }, [fetchEvents, pollInterval])

  return {
    events: data?.events ?? [],
    sessionIds: data?.session_ids ?? [],
    sessions: data?.sessions ?? [],
    total: data?.total ?? 0,
    maxTurn: data?.max_turn ?? 0,
    isLoading,
    error,
    refetch: fetchEvents,
  }
}

export type { AgentEventType, AgentHubEvent }
