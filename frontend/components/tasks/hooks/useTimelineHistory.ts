import { useCallback, useEffect, useRef, useState } from 'react'
import { type Event, getEventsByTask } from '@/lib/api/events'
import type { TimelineMessage } from '../TimelineEvent'

interface UseTimelineHistoryOptions {
  taskId: string
  projectId?: string
  onLastSequence?: (sequence: number) => void
}

export function useTimelineHistory({
  taskId,
  projectId,
  onLastSequence,
}: UseTimelineHistoryOptions) {
  const [historicalEvents, setHistoricalEvents] = useState<TimelineMessage[]>(
    [],
  )
  const [isLoading, setIsLoading] = useState(false)

  // Use ref to avoid onLastSequence in deps (prevents infinite loops)
  const onLastSequenceRef = useRef(onLastSequence)
  onLastSequenceRef.current = onLastSequence

  const eventToTimelineMessage = useCallback(
    (event: Event, index: number): TimelineMessage => {
      const typeMap: Record<string, TimelineMessage['type']> = {
        log: 'log',
        progress: 'progress',
        model_change: 'model_change',
        chat_message: 'chat_message',
        error: 'error',
      }
      return {
        type: typeMap[event.event_type] || 'log',
        task_id: event.trace_id,
        data: {
          message: event.message,
          level: event.level,
          source: event.source,
          ...event.attributes,
        },
        timestamp: event.timestamp,
        sequence: index,
        trace_id: event.trace_id,
        span_id: event.span_id,
        visibility: event.visibility,
      }
    },
    [],
  )

  useEffect(() => {
    if (!projectId) return

    const fetchHistory = async () => {
      setIsLoading(true)
      try {
        const events = await getEventsByTask(projectId, taskId, {
          visibility: 'user',
          limit: 500,
        })
        const converted = events.map(eventToTimelineMessage)
        setHistoricalEvents(converted)
        if (converted.length > 0 && onLastSequenceRef.current) {
          onLastSequenceRef.current(converted.length)
        }
      } catch (err) {
        console.error('Failed to fetch historical events:', err)
      } finally {
        setIsLoading(false)
      }
    }

    fetchHistory()
  }, [projectId, taskId, eventToTimelineMessage])

  return {
    historicalEvents,
    isLoading,
  }
}
