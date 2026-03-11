import { useCallback, useEffect, useRef, useState } from 'react'
import { fetchTask, type Task } from '@/lib/api/tasks'
import { POLL_RAPID } from '@/lib/polling'
import { getErrorMessage } from '@/lib/utils'

interface UseEnrichmentPollingProps {
  projectId: string
  initialTask: Task
  onComplete: (task: Task) => void
  onError: (error: string) => void
}

export function useEnrichmentPolling({
  projectId,
  initialTask,
  onComplete,
  onError,
}: UseEnrichmentPollingProps) {
  const [task, setTask] = useState<Task>(initialTask)
  const [startTime] = useState(Date.now())
  const [elapsedMs, setElapsedMs] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const pollRef = useRef<NodeJS.Timeout | null>(null)
  const progressRef = useRef<NodeJS.Timeout | null>(null)

  // Poll for task updates
  const pollTask = useCallback(async () => {
    try {
      const updatedTask = await fetchTask(projectId, task.id)
      setTask(updatedTask)
      setError(null)

      if (updatedTask.enrichment_status === 'review') {
        onComplete(updatedTask)
      } else if (updatedTask.enrichment_status === 'failed') {
        setError(updatedTask.error_message || 'Enrichment failed')
        onError(updatedTask.error_message || 'Enrichment failed')
      }
    } catch (err) {
      setError(getErrorMessage(err, 'Failed to refresh enrichment status'))
    }
  }, [projectId, task.id, onComplete, onError])

  // Start polling on mount
  useEffect(() => {
    if (task.enrichment_status !== 'enriching') return

    pollRef.current = setInterval(pollTask, POLL_RAPID)

    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
    }
  }, [task.enrichment_status, pollTask])

  // Progress animation timer
  useEffect(() => {
    if (task.enrichment_status !== 'enriching') return

    progressRef.current = setInterval(() => {
      setElapsedMs(Date.now() - startTime)
    }, 100)

    return () => {
      if (progressRef.current) clearInterval(progressRef.current)
    }
  }, [task.enrichment_status, startTime])

  const resetPolling = useCallback(() => {
    setError(null)
    setElapsedMs(0)
  }, [])

  return {
    task,
    elapsedMs,
    error,
    setError,
    pollTask,
    resetPolling,
  }
}
