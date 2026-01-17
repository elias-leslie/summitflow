'use client'

import { useCallback, useEffect, useRef, useState } from 'react'

// Observation types from the API
export type ObservationType =
  | 'bugfix'
  | 'feature'
  | 'refactor'
  | 'change'
  | 'discovery'
  | 'decision'

export type ConceptType =
  | 'how-it-works'
  | 'why-it-exists'
  | 'what-changed'
  | 'problem-solution'
  | 'gotcha'
  | 'pattern'
  | 'trade-off'

export interface Observation {
  id: string
  project_id: string
  session_id: string
  agent_type: string
  observation_type: ObservationType
  concepts: ConceptType[]
  title: string
  subtitle: string | null
  narrative: string | null
  facts: Record<string, unknown>[] | null
  files_read: string[] | null
  files_modified: string[] | null
  tool_name: string
  tool_input: Record<string, unknown> | null
  discovery_tokens: number | null
  extracted_by: string | null
  created_at: string
}

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected'

interface UseMemoryStreamOptions {
  /**
   * Project ID to filter observations. If undefined, shows all projects.
   */
  projectId?: string
  /**
   * Session ID to filter observations within a project.
   */
  sessionId?: string
  /**
   * Maximum number of observations to keep in memory.
   * @default 100
   */
  maxObservations?: number
  /**
   * Whether to auto-connect on mount.
   * @default true
   */
  autoConnect?: boolean
}

interface UseMemoryStreamReturn {
  /**
   * Array of observations, newest first.
   */
  observations: Observation[]
  /**
   * Current connection status.
   */
  status: ConnectionStatus
  /**
   * Error message if any.
   */
  error: string | null
  /**
   * Manually connect to the stream.
   */
  connect: () => void
  /**
   * Manually disconnect from the stream.
   */
  disconnect: () => void
  /**
   * Clear all observations.
   */
  clearObservations: () => void
}

/**
 * Hook for subscribing to real-time observation updates via SSE.
 *
 * Supports both project-specific streams (via SSE) and global observation
 * polling when no project is specified.
 */
export function useMemoryStream(
  options: UseMemoryStreamOptions = {},
): UseMemoryStreamReturn {
  const {
    projectId,
    sessionId,
    maxObservations = 100,
    autoConnect = true,
  } = options

  const [observations, setObservations] = useState<Observation[]>([])
  const [status, setStatus] = useState<ConnectionStatus>('disconnected')
  const [error, setError] = useState<string | null>(null)

  const eventSourceRef = useRef<EventSource | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const pollIntervalRef = useRef<NodeJS.Timeout | null>(null)
  const lastObservationIdRef = useRef<string | null>(null)

  // Add a new observation to the list
  const addObservation = useCallback(
    (observation: Observation) => {
      // Filter by session if specified
      if (sessionId && observation.session_id !== sessionId) {
        return
      }

      setObservations((prev) => {
        // Avoid duplicates
        if (prev.some((o) => o.id === observation.id)) {
          return prev
        }
        // Add to front (newest first), keep max observations
        return [observation, ...prev].slice(0, maxObservations)
      })
    },
    [sessionId, maxObservations],
  )

  // SSE connection for project-specific streams
  const connectSSE = useCallback(() => {
    if (!projectId) return

    if (eventSourceRef.current) {
      eventSourceRef.current.close()
    }

    setStatus('reconnecting')
    setError(null)

    const url = `/api/projects/${projectId}/observations/stream`
    const eventSource = new EventSource(url)
    eventSourceRef.current = eventSource

    eventSource.addEventListener('connected', () => {
      setStatus('connected')
      setError(null)
    })

    eventSource.addEventListener('observation', (event) => {
      try {
        const observation = JSON.parse(event.data) as Observation
        addObservation(observation)
      } catch (err) {
        console.error('Failed to parse observation:', err)
      }
    })

    // Legacy event name from observation_created
    eventSource.addEventListener('observation_created', (event) => {
      try {
        const observation = JSON.parse(event.data) as Observation
        addObservation(observation)
      } catch (err) {
        console.error('Failed to parse observation:', err)
      }
    })

    eventSource.addEventListener('heartbeat', () => {
      // Keep alive, reset error state if any
      if (status !== 'connected') {
        setStatus('connected')
      }
    })

    eventSource.onerror = () => {
      setStatus('disconnected')
      eventSource.close()
      eventSourceRef.current = null

      // Reconnect after delay
      if (!reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null
          connectSSE()
        }, 5000)
      }
    }
  }, [projectId, addObservation, status])

  // Polling for global observations (when no project specified)
  const startPolling = useCallback(() => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
    }

    const fetchObservations = async () => {
      try {
        const params = new URLSearchParams({ limit: '20' })
        if (sessionId) {
          params.set('session_id', sessionId)
        }

        // Use global endpoint
        const response = await fetch(`/api/observations?${params}`)
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        const data = (await response.json()) as Observation[]

        // Only update if we have new observations
        if (data.length > 0 && data[0].id !== lastObservationIdRef.current) {
          lastObservationIdRef.current = data[0].id

          setObservations((prev) => {
            // Merge new observations, avoiding duplicates
            const existingIds = new Set(prev.map((o) => o.id))
            const newObs = data.filter((o) => !existingIds.has(o.id))
            if (newObs.length === 0) return prev
            return [...newObs, ...prev].slice(0, maxObservations)
          })
        }

        setStatus('connected')
        setError(null)
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to fetch')
        setStatus('disconnected')
      }
    }

    // Initial fetch
    fetchObservations()

    // Poll every 5 seconds
    pollIntervalRef.current = setInterval(fetchObservations, 5000)
    setStatus('reconnecting')
  }, [sessionId, maxObservations])

  // Main connect function
  const connect = useCallback(() => {
    if (projectId) {
      connectSSE()
    } else {
      startPolling()
    }
  }, [projectId, connectSSE, startPolling])

  // Disconnect function
  const disconnect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close()
      eventSourceRef.current = null
    }
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current)
      pollIntervalRef.current = null
    }
    setStatus('disconnected')
  }, [])

  // Clear observations
  const clearObservations = useCallback(() => {
    setObservations([])
    lastObservationIdRef.current = null
  }, [])

  // Load initial observations
  useEffect(() => {
    const loadInitial = async () => {
      try {
        const params = new URLSearchParams({ limit: '50' })
        if (sessionId) {
          params.set('session_id', sessionId)
        }

        // Use appropriate endpoint based on projectId
        const url = projectId
          ? `/api/projects/${projectId}/observations?${params}`
          : `/api/observations?${params}`

        const response = await fetch(url)
        if (response.ok) {
          const data = await response.json()
          setObservations(data)
          if (data.length > 0) {
            lastObservationIdRef.current = data[0].id
          }
        }
      } catch (err) {
        console.error('Failed to load initial observations:', err)
      }
    }

    loadInitial()
  }, [projectId, sessionId])

  // Auto-connect effect
  useEffect(() => {
    if (autoConnect) {
      connect()
    }

    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  // Reconnect when projectId changes
  useEffect(() => {
    disconnect()
    clearObservations()
    if (autoConnect) {
      connect()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoConnect, clearObservations, connect, disconnect])

  return {
    observations,
    status,
    error,
    connect,
    disconnect,
    clearObservations,
  }
}
