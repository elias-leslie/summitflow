'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected'

export interface Observation {
  id: string
  project_id: string
  session_id: string
  agent_type: string
  observation_type: string
  concepts: string[]
  title: string
  subtitle: string | null
  narrative: string | null
  facts: Record<string, unknown>[] | null
  files_read: string[] | null
  files_modified: string[] | null
  tool_name: string
  tool_input: Record<string, unknown> | null
  discovery_tokens: number | null
  created_at: string
}

export interface UseObservationStreamOptions {
  projectId: string
  sessionId?: string
  onObservation?: (observation: Observation) => void
  reconnectDelay?: number
}

export interface UseObservationStreamResult {
  status: ConnectionStatus
  connect: () => void
  disconnect: () => void
}

/**
 * Hook for connecting to the observation SSE stream.
 * Handles connection, reconnection, and status management.
 */
export function useObservationStream({
  projectId,
  sessionId,
  onObservation,
  reconnectDelay = 5000,
}: UseObservationStreamOptions): UseObservationStreamResult {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const onObservationRef = useRef(onObservation)

  // Keep callback ref updated to avoid reconnection on callback change
  useEffect(() => {
    onObservationRef.current = onObservation
  }, [onObservation])

  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    setStatus('disconnected')
  }, [])

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    setStatus('reconnecting')

    const url = `/api/projects/${projectId}/observations/stream`
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.addEventListener('connected', () => {
      setStatus('connected')
    })

    eventSource.addEventListener('observation', (event) => {
      try {
        const observation = JSON.parse(event.data) as Observation

        // Filter by session if specified
        if (sessionId && observation.session_id !== sessionId) {
          return
        }

        onObservationRef.current?.(observation)
      } catch (err) {
        console.error('Failed to parse observation:', err)
      }
    })

    eventSource.addEventListener('heartbeat', () => {
      // Keep alive, ensure we're marked as connected
      setStatus((prev) => (prev !== 'connected' ? 'connected' : prev))
    })

    eventSource.onerror = () => {
      setStatus('disconnected')
      eventSource.close()
      eventSourceRef.current = null

      // Reconnect after delay
      if (!reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null
          connect()
        }, reconnectDelay)
      }
    }
  }, [projectId, sessionId, reconnectDelay])

  // Auto-connect on mount and cleanup on unmount
  useEffect(() => {
    connect()
    return disconnect
  }, [connect, disconnect])

  return { status, connect, disconnect }
}
