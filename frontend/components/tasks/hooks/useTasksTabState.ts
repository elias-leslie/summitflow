import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import type { Task } from '@/lib/api'

interface UseTasksTabStateProps {
  refetch: () => void
  handleTaskUpdated: (task: Task) => void
}

export function useTasksTabState({
  refetch,
  handleTaskUpdated,
}: UseTasksTabStateProps) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const urlTaskId = searchParams.get('task')
  const urlModal = searchParams.get('modal')

  // Modal state
  const [modalTaskId, setModalTaskId] = useState<string | null>(urlTaskId)
  const [modalOpen, setModalOpen] = useState(!!urlTaskId)
  const [selectedTask, setSelectedTask] = useState<Task | null>(null)
  const [showCreate, setShowCreate] = useState(urlModal === 'create-task')
  const [enrichingTask, setEnrichingTask] = useState<Task | null>(null)
  const [reviewingTask, setReviewingTask] = useState<Task | null>(null)

  // Helper to update URL params
  const updateUrlParams = useCallback(
    (params: Record<string, string | null>) => {
      const newParams = new URLSearchParams(searchParams.toString())
      Object.entries(params).forEach(([key, value]) => {
        if (value === null) {
          newParams.delete(key)
        } else {
          newParams.set(key, value)
        }
      })
      const query = newParams.toString()
      router.replace(`${pathname}${query ? `?${query}` : ''}`, {
        scroll: false,
      })
    },
    [router, pathname, searchParams],
  )

  // Handle URL task param changes
  useEffect(() => {
    if (urlTaskId) {
      setModalTaskId(urlTaskId)
      setModalOpen(true)
    }
  }, [urlTaskId])

  // Handle URL modal param changes
  useEffect(() => {
    if (urlModal === 'create-task') {
      setShowCreate(true)
    }
  }, [urlModal])

  // Task lifecycle handlers
  const handleTaskCreated = useCallback(
    (task: Task, mode: 'queue' | 'verify') => {
      if (mode === 'verify' && task.enrichment_status === 'review') {
        setReviewingTask(task)
      } else if (mode === 'queue' && task.enrichment_status === 'enriching') {
        setEnrichingTask(task)
      }
      refetch()
    },
    [refetch],
  )

  const handleEnrichmentComplete = useCallback(
    (task: Task) => {
      setEnrichingTask(null)
      if (task.enrichment_status === 'review') {
        setReviewingTask(task)
      }
      refetch()
    },
    [refetch],
  )

  const handleTaskAccepted = useCallback(
    (acceptedTask: Task) => {
      setReviewingTask(null)
      handleTaskUpdated(acceptedTask)
      refetch()
    },
    [refetch, handleTaskUpdated],
  )

  const handleTaskClick = useCallback(
    (task: Task) => {
      setModalTaskId(task.id)
      setSelectedTask(task)
      setModalOpen(true)
      updateUrlParams({ task: task.id })
    },
    [updateUrlParams],
  )

  const handleModalOpenChange = useCallback(
    (open: boolean) => {
      setModalOpen(open)
      if (!open) {
        updateUrlParams({ task: null })
      }
    },
    [updateUrlParams],
  )

  const handleShowCreateChange = useCallback(
    (open: boolean) => {
      setShowCreate(open)
      updateUrlParams({ modal: open ? 'create-task' : null })
    },
    [updateUrlParams],
  )

  const handleNewTask = useCallback(() => {
    setShowCreate(true)
    updateUrlParams({ modal: 'create-task' })
  }, [updateUrlParams])

  const handleTaskUpdate = useCallback(
    (task: Task) => {
      setSelectedTask(task)
      handleTaskUpdated(task)
    },
    [handleTaskUpdated],
  )

  return {
    // Modal state
    modalTaskId,
    modalOpen,
    selectedTask,
    showCreate,
    enrichingTask,
    reviewingTask,
    // Handlers
    handleTaskCreated,
    handleEnrichmentComplete,
    handleTaskAccepted,
    handleTaskClick,
    handleModalOpenChange,
    handleShowCreateChange,
    handleNewTask,
    handleTaskUpdate,
    setEnrichingTask,
    setReviewingTask,
  }
}
