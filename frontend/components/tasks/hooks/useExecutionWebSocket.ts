import { useCallback, useEffect, useRef, useState } from 'react'
import { getWsUrl } from '@/lib/api-config'
import type { TimelineMessage } from '../TimelineEvent'

export function getWebSocketUrl(taskId: string, fromSequence?: number): string {
  const path = `/ws/execution/${taskId}${fromSequence ? `?from_sequence=${fromSequence}` : ''}`
  return getWsUrl(path)
}

interface UseExecutionWebSocketOptions {
  taskId: string
  autoConnect: boolean
  onMessage: (message: TimelineMessage) => void
  onScrollToBottom: () => void
}

export function useExecutionWebSocket({
  taskId,
  autoConnect,
  onMessage,
  onScrollToBottom,
}: UseExecutionWebSocketOptions) {
  const [isConnected, setIsConnected] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const wsRef = useRef<WebSocket | null>(null)
  const lastSequenceRef = useRef<number>(0)
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null)
  const reconnectAttemptRef = useRef<number>(0)
  const maxReconnectDelay = 30000

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
          const delay = Math.min(1000 * 2 ** attempt, maxReconnectDelay)
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
