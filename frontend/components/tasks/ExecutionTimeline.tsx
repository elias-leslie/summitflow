'use client'

import { AlertCircle, Loader2 } from 'lucide-react'
import { useCallback, useMemo, useRef, useState } from 'react'
import { useExecutionWebSocketStream } from '@/hooks/useExecutionWebSocketStream'
import { useTimelineHistory } from './hooks/useTimelineHistory'
import { useVoiceRecording } from './hooks/useVoiceRecording'
import { TimelineChatInput } from './TimelineChatInput'
import { TimelineEvent, type TimelineMessage } from './TimelineEvent'
import { TimelineHeader } from './TimelineHeader'

interface ExecutionTimelineProps {
  taskId: string
  /** Project ID for fetching historical events */
  projectId?: string
  /** Whether to auto-connect on mount */
  autoConnect?: boolean
  /** Show chat input at bottom */
  showChatInput?: boolean
  /** Whether chat input is enabled (task must be executing) */
  chatEnabled?: boolean
  /** Optional class name */
  className?: string
  /** Max height for timeline (default: 500px, use 'none' for no limit) */
  maxHeight?: string
}

export function ExecutionTimeline({
  taskId,
  projectId,
  autoConnect = true,
  showChatInput = false,
  chatEnabled = false,
  className = '',
  maxHeight = '500px',
}: ExecutionTimelineProps) {
  const [messages, setMessages] = useState<TimelineMessage[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)
  const seenSequences = useRef<Set<number>>(new Set())

  const getEventKey = useCallback((message: TimelineMessage) => {
    const eventId =
      message.event_id ||
      (typeof message.data?.event_id === 'string' ? message.data.event_id : undefined)
    if (eventId) {
      return `event:${eventId}`
    }

    const msg = typeof message.data?.message === 'string' ? message.data.message : ''
    const src = typeof message.data?.source === 'string' ? message.data.source : ''
    return `${message.type}:${message.timestamp}:${message.sequence}:${src}:${msg}`
  }, [])

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      // Use requestAnimationFrame to ensure DOM is updated
      requestAnimationFrame(() => {
        if (scrollRef.current) {
          scrollRef.current.scrollTop = scrollRef.current.scrollHeight
        }
      })
    }
  }, [])

  // Handle new WebSocket message with deduplication
  const handleMessage = useCallback((message: TimelineMessage) => {
    // Deduplicate by sequence number
    if (message.sequence > 0 && seenSequences.current.has(message.sequence)) {
      return
    }
    if (message.sequence > 0) {
      seenSequences.current.add(message.sequence)
    }
    setMessages((prev) => [...prev, message])
  }, [])

  // Connect to WebSocket
  const { isConnected, error, connect, sendChatMessage, setLastSequence } =
    useExecutionWebSocketStream({
      taskId,
      autoConnect,
      onMessage: handleMessage,
      onScrollToBottom: scrollToBottom,
    })

  // Fetch historical events (hook uses ref internally for callback stability)
  const {
    historicalEvents,
    historyError,
    isLoading: isLoadingHistory,
  } = useTimelineHistory({
    taskId,
    projectId,
    onLastSequence: setLastSequence,
  })

  // Voice recording
  const {
    isRecording,
    error: voiceError,
    toggleRecording,
  } = useVoiceRecording({
    onTranscription: sendChatMessage,
  })

  // Combine historical and live events, sorted by timestamp and deduplicated
  const allEvents = useMemo(() => {
    const combined = [...historicalEvents, ...messages]

    // Sort by timestamp (ascending - oldest first)
    combined.sort((a, b) => {
      const timeA = new Date(a.timestamp).getTime()
      const timeB = new Date(b.timestamp).getTime()
      if (timeA !== timeB) return timeA - timeB
      return a.sequence - b.sequence
    })

    // Deduplicate using persisted event ids when available.
    const seen = new Set<string>()
    return combined.filter((event) => {
      const key = getEventKey(event)
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
  }, [historicalEvents, messages, getEventKey])

  // Track height style
  const heightStyle = maxHeight === 'none'
    ? { minHeight: '200px' }
    : { minHeight: '200px', maxHeight }

  return (
    <div className={`flex flex-col ${className}`}>
      <TimelineHeader
        isConnected={isConnected}
        error={error}
        autoConnect={autoConnect}
        onReconnect={connect}
      />

      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto bg-slate-950/40 rounded-b-lg border border-slate-800/50 border-t-0"
        style={heightStyle}
      >
        {historyError && (
          <div className="border-b border-amber-900/40 bg-amber-950/20 px-3 py-2 text-xs text-amber-300">
            {historyError}
          </div>
        )}
        {isLoadingHistory ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            <Loader2 className="h-5 w-5 animate-spin mb-2" />
            <span className="text-sm">Loading events...</span>
          </div>
        ) : allEvents.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-slate-600 py-8">
            {error ? (
              <>
                <AlertCircle className="h-5 w-5 mb-2 text-amber-500" />
                <span className="text-sm text-amber-500">{error}</span>
              </>
            ) : isConnected ? (
              <>
                <Loader2 className="h-5 w-5 animate-spin mb-2" />
                <span className="text-sm">Waiting for execution events...</span>
              </>
            ) : (
              <span className="text-sm">No execution events recorded</span>
            )}
          </div>
        ) : (
          <div className="py-2">
            {allEvents.map((message, idx) => (
              <TimelineEvent
                key={`${getEventKey(message)}-${idx}`}
                message={message}
              />
            ))}
          </div>
        )}
      </div>

      {showChatInput && (
        <TimelineChatInput
          chatEnabled={chatEnabled}
          isRecording={isRecording}
          voiceError={voiceError}
          onSendMessage={sendChatMessage}
          onToggleVoiceRecording={toggleRecording}
        />
      )}
    </div>
  )
}

// Export helper types for external use
export type { TimelineMessage }
