import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'
import type { Task } from '@/lib/api'
import { buildUrlWithUpdatedSearchParams } from '@/lib/search-params'

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
      router.replace(
        buildUrlWithUpdatedSearchParams(pathname, searchParams, params),
        {
          scroll: false,
        },
      )
    },
    [router, pathname, searchParams],
  )

  // Handle URL task param changes
  useEffect(() => {
    if (urlTaskId) {
      setModalTaskId(urlTaskId)
      setModalOpen(true)
      return
    }
    setModalTaskId(null)
    setSelectedTask(null)
    setModalOpen(false)
  }, [urlTaskId])

  // Handle URL modal param changes
  useEffect(() => {
    setShowCreate(urlModal === 'create-task')
  }, [urlModal])

  // Task lifecycle handlers
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
