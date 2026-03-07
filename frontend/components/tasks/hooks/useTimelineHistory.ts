import { useCallback, useEffect, useRef, useState } from 'react'
import { type Event, getEventsForTrace } from '@/lib/api/events'
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
      const attributes = event.attributes || {}
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
          event_id: event.id,
          ...attributes,
        },
        timestamp: event.timestamp,
        sequence:
          typeof attributes.sequence === 'number' ? attributes.sequence : index,
        event_id: event.id,
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
        const events: Event[] = []
        const pageSize = 1000
        let after: string | undefined

        while (true) {
          const page = await getEventsForTrace(projectId, taskId, {
            visibility: 'user',
            after,
            limit: pageSize,
          })
          if (page.length === 0) {
            break
          }
          events.push(...page)
          after = page[page.length - 1]?.timestamp
          if (page.length < pageSize) {
            break
          }
        }

        const converted = events.map(eventToTimelineMessage)
        setHistoricalEvents(converted)
        onLastSequenceRef.current?.(0)
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
