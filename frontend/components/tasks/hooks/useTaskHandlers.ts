import { useMutation } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import type { Task } from '@/lib/api'
import { deleteTask, deleteTasks, executeTasks } from '@/lib/api/tasks'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'
import { getErrorMessage } from '@/lib/utils'

export function useTaskHandlers(projectId: string) {
  const { syncDeletedTask, syncUpdatedTask } = useTaskMutationSync(projectId)
  const [deleteConfirmTask, setDeleteConfirmTask] = useState<Task | null>(null)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)

  // Delete mutations
  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(projectId, taskId),
    onSuccess: (_, taskId) => {
      syncDeletedTask(taskId)
      setDeleteConfirmTask(null)
      toast.success('Task deleted')
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to delete task'))
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (taskIds: string[]) => deleteTasks(projectId, taskIds),
    onSuccess: (_, taskIds) => {
      for (const taskId of taskIds) {
        syncDeletedTask(taskId)
      }
      setBulkDeleteConfirm(false)
      toast.success(
        taskIds.length === 1
          ? 'Task deleted'
          : `${taskIds.length} tasks deleted`,
      )
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to delete selected tasks'))
    },
  })

  const bulkExecuteMutation = useMutation({
    mutationFn: (taskIds: string[]) => executeTasks(projectId, taskIds),
    onSuccess: ({ queued, failed }) => {
      for (const task of queued) {
        syncUpdatedTask(task)
      }
      if (queued.length > 0) {
        toast.success(
          queued.length === 1
            ? 'Task queued for execution'
            : `${queued.length} tasks queued for execution`,
        )
      }
      if (failed.length > 0) {
        toast.error(
          failed.length === 1
            ? `Failed to queue ${failed[0].taskId}`
            : `${failed.length} tasks failed to queue`,
        )
      }
    },
    onError: (error) => {
      toast.error(getErrorMessage(error, 'Failed to queue selected tasks'))
    },
  })

  // Task update handler
  const handleTaskUpdated = useCallback(
    (updatedTask: Task) => {
      syncUpdatedTask(updatedTask)
    },
    [syncUpdatedTask],
  )

  return {
    deleteConfirmTask,
    setDeleteConfirmTask,
    bulkDeleteConfirm,
    setBulkDeleteConfirm,
    deleteMutation,
    bulkDeleteMutation,
    bulkExecuteMutation,
    handleTaskUpdated,
  }
}
