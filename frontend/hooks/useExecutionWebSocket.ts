'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import type {
  ExecutionLog,
  ExecutionState,
} from '@/components/kanban/ExecutionPanel'
import type { TimelineMessage } from '@/components/tasks/TimelineEvent'
import { getWsUrl } from '@/lib/api-config'

// ============================================================================
// Shared Utilities
// ============================================================================

export function getWebSocketUrl(taskId: string, fromSequence?: number): string {
  const path = `/ws/execution/${taskId}${fromSequence ? `?from_sequence=${fromSequence}` : ''}`
  return getWsUrl(path)
}

// Message types from backend
type MessageType =
  | 'log'
  | 'progress'
  | 'model_change'
  | 'chat_message'
  | 'stop_signal'
  | 'connected'
  | 'error'

interface WebSocketMessage {
  type: MessageType
  task_id: string
  data: Record<string, unknown>
  timestamp: string
  sequence: number
}

interface UseExecutionWebSocketOptions {
  taskId: string
  enabled?: boolean
  onError?: (error: string) => void
}

interface UseExecutionWebSocketReturn {
  execution: ExecutionState
  connected: boolean
  connecting: boolean
  sendMessage: (message: string) => void
  sendStop: () => void
}

// Exponential backoff config
const INITIAL_RECONNECT_DELAY = 1000
const MAX_RECONNECT_DELAY = 30000
const RECONNECT_MULTIPLIER = 2

export function useExecutionWebSocket({
  taskId,
  enabled = true,
  onError,
}: UseExecutionWebSocketOptions): UseExecutionWebSocketReturn {
  const wsRef = useRef<WebSocket | null>(null)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectDelayRef = useRef(INITIAL_RECONNECT_DELAY)
  const lastSequenceRef = useRef(0)

  const [connected, setConnected] = useState(false)
  const [connecting, setConnecting] = useState(false)
  const [execution, setExecution] = useState<ExecutionState>({
    status: 'idle',
    progress: 0,
    currentModel: 'Flash',
    logs: [],
  })

  const connect = useCallback(() => {
    if (!enabled || !taskId) return
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    setConnecting(true)

    const ws = new WebSocket(getWebSocketUrl(taskId, lastSequenceRef.current || undefined))
    wsRef.current = ws

    ws.onopen = () => {
      setConnected(true)
      setConnecting(false)
      reconnectDelayRef.current = INITIAL_RECONNECT_DELAY
    }

    ws.onclose = () => {
      setConnected(false)
      setConnecting(false)
      wsRef.current = null

      // Schedule reconnection with exponential backoff
      if (enabled) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectDelayRef.current = Math.min(
            reconnectDelayRef.current * RECONNECT_MULTIPLIER,
            MAX_RECONNECT_DELAY,
          )
          connect()
        }, reconnectDelayRef.current)
      }
    }

    ws.onerror = () => {
      onError?.('WebSocket connection error')
    }

    ws.onmessage = (event) => {
      try {
        const msg: WebSocketMessage = JSON.parse(event.data)
        lastSequenceRef.current = msg.sequence

        switch (msg.type) {
          case 'connected':
            setExecution((prev) => ({ ...prev, status: 'running' }))
            break

          case 'log': {
            const logData = msg.data as { level?: string; message?: string }
            const newLog: ExecutionLog = {
              id: `${msg.sequence}`,
              timestamp: msg.timestamp,
              level: (logData.level as ExecutionLog['level']) || 'info',
              message: String(logData.message || ''),
            }
            setExecution((prev) => ({
              ...prev,
              logs: [...prev.logs.slice(-99), newLog], // Keep last 100 logs
            }))
            break
          }

          case 'progress': {
            const progressData = msg.data as {
              completed_subtasks?: number
              total_subtasks?: number
              status?: string
            }
            const completed = progressData.completed_subtasks || 0
            const total = progressData.total_subtasks || 1
            const progress = Math.round((completed / total) * 100)
            setExecution((prev) => ({
              ...prev,
              progress,
              currentStep: progressData.status,
            }))
            break
          }

          case 'model_change': {
            const modelData = msg.data as { model?: string }
            setExecution((prev) => ({
              ...prev,
              currentModel: String(modelData.model || prev.currentModel),
            }))
            break
          }

          case 'stop_signal':
            setExecution((prev) => ({ ...prev, status: 'stopped' }))
            break

          case 'error': {
            const errorData = msg.data as { error?: string }
            onError?.(String(errorData.error || 'Unknown error'))
            break
          }

          case 'chat_message':
            // Chat messages from other clients - could show in logs
            break
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e)
      }
    }
  }, [taskId, enabled, onError])

  // Connect on mount, disconnect on unmount
  useEffect(() => {
    connect()

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current)
      }
      if (wsRef.current) {
        wsRef.current.close()
        wsRef.current = null
      }
    }
  }, [connect])

  const sendMessage = useCallback((message: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'chat_message',
          data: { message },
        }),
      )
    }
  }, [])

  const sendStop = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'stop_signal',
          data: {},
        }),
      )
    }
  }, [])

  return {
    execution,
    connected,
    connecting,
    sendMessage,
    sendStop,
  }
}

// ============================================================================
// useExecutionWebSocketStream — Raw stream variant for ExecutionTimeline
// ============================================================================

interface UseExecutionWebSocketStreamOptions {
  taskId: string
  autoConnect: boolean
  onMessage: (message: TimelineMessage) => void
  onScrollToBottom: () => void
}

export function useExecutionWebSocketStream({
  taskId,
  autoConnect,
  onMessage,
  onScrollToBottom,
}: UseExecutionWebSocketStreamOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const lastSequenceRef = useRef<number>(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptRef = useRef<number>(0)

  const connect = useCallback(() => {
    if (wsRef.current?.readyState === WebSocket.OPEN) return

    try {
      const ws = new WebSocket(getWebSocketUrl(taskId, lastSequenceRef.current))

      ws.onopen = () => {
        setIsConnected(true)
        setError(null)
        reconnectAttemptRef.current = 0
      }

      ws.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data) as TimelineMessage
          lastSequenceRef.current = Math.max(
            lastSequenceRef.current,
            message.sequence,
          )
          onMessage(message)
          setTimeout(onScrollToBottom, 10)
        } catch (err) {
          console.error('Failed to parse message:', err)
        }
      }

      ws.onerror = () => {
        setError('Connection error')
        setIsConnected(false)
      }

      ws.onclose = () => {
        setIsConnected(false)
        if (autoConnect) {
          const attempt = reconnectAttemptRef.current
          const delay = Math.min(
            INITIAL_RECONNECT_DELAY * RECONNECT_MULTIPLIER ** attempt,
            MAX_RECONNECT_DELAY,
          )
          reconnectAttemptRef.current = attempt + 1
          reconnectTimeoutRef.current = setTimeout(connect, delay)
        }
      }

      wsRef.current = ws
    } catch (err) {
      console.error('Failed to connect:', err)
      setError('Failed to connect to execution stream')
    }
  }, [taskId, autoConnect, onMessage, onScrollToBottom])

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current)
      reconnectTimeoutRef.current = null
    }
    if (wsRef.current) {
      wsRef.current.close()
      wsRef.current = null
    }
  }, [])

  const sendChatMessage = useCallback((text: string) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(
        JSON.stringify({
          type: 'chat_message',
          data: { message: text, sender: 'user' },
        }),
      )
    }
  }, [])

  useEffect(() => {
    if (autoConnect) {
      connect()
    }
    return () => {
      disconnect()
    }
  }, [autoConnect, connect, disconnect])

  return {
    isConnected,
    error,
    connect,
    disconnect,
    sendChatMessage,
    setLastSequence: (seq: number) => {
      lastSequenceRef.current = seq
    },
  }
}
