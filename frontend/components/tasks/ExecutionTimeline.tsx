'use client'

import { AlertCircle, Loader2 } from 'lucide-react'
import { useCallback, useRef, useState } from 'react'
import { useExecutionWebSocket } from './hooks/useExecutionWebSocket'
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
}

export function ExecutionTimeline({
  taskId,
  projectId,
  autoConnect = true,
  showChatInput = false,
  chatEnabled = false,
  className = '',
}: ExecutionTimelineProps) {
  const [messages, setMessages] = useState<TimelineMessage[]>([])
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll to bottom when new messages arrive
  const scrollToBottom = useCallback(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [])

  // Handle new WebSocket message
  const handleMessage = useCallback((message: TimelineMessage) => {
    setMessages((prev) => [...prev, message])
  }, [])

  // Fetch historical events
  const { historicalEvents, isLoading: isLoadingHistory } = useTimelineHistory({
    taskId,
    projectId,
    onLastSequence: (seq) => {
      setLastSequence(seq)
    },
  })

  // Connect to WebSocket
  const { isConnected, error, connect, sendChatMessage, setLastSequence } =
    useExecutionWebSocket({
      taskId,
      autoConnect,
      onMessage: handleMessage,
      onScrollToBottom: scrollToBottom,
    })

  // Voice recording
  const {
    isRecording,
    error: voiceError,
    toggleRecording,
  } = useVoiceRecording({
    onTranscription: sendChatMessage,
  })

  // Combine historical and live events
  const allEvents = [...historicalEvents, ...messages]

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
        className="flex-1 overflow-y-auto min-h-[200px] max-h-[400px] bg-slate-950/30"
      >
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
                key={`${message.sequence}-${idx}`}
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

// Export helper types and methods for external use
export type { TimelineMessage }
export { getWebSocketUrl } from './hooks/useExecutionWebSocket'
