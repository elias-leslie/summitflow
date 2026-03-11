import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { deleteTask, deleteTasks } from '@/lib/api/tasks'
import type { Task } from '@/lib/api'
import {
  invalidateTaskQueries,
  removeTaskFromTaskLists,
  syncTaskInTaskLists,
} from '@/lib/task-cache'

export function useTaskHandlers(projectId: string) {
  const queryClient = useQueryClient()
  const [deleteConfirmTask, setDeleteConfirmTask] = useState<Task | null>(null)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)

  // Delete mutations
  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(projectId, taskId),
    onSuccess: (_, taskId) => {
      removeTaskFromTaskLists(queryClient, projectId, taskId)
      void invalidateTaskQueries(queryClient, projectId)
      setDeleteConfirmTask(null)
      toast.success('Task deleted')
    },
    onError: (error) => {
      console.error('Failed to delete task:', error)
      toast.error('Failed to delete task')
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (taskIds: string[]) => deleteTasks(projectId, taskIds),
    onSuccess: (_, taskIds) => {
      for (const taskId of taskIds) {
        removeTaskFromTaskLists(queryClient, projectId, taskId)
      }
      void invalidateTaskQueries(queryClient, projectId)
      setBulkDeleteConfirm(false)
      toast.success(
        taskIds.length === 1 ? 'Task deleted' : `${taskIds.length} tasks deleted`,
      )
    },
    onError: (error) => {
      console.error('Failed to delete tasks:', error)
      toast.error('Failed to delete selected tasks')
    },
  })

  // Task update handler
  const handleTaskUpdated = useCallback(
    (updatedTask: Task) => {
      syncTaskInTaskLists(queryClient, projectId, updatedTask)
      void invalidateTaskQueries(queryClient, projectId)
    },
    [queryClient, projectId],
  )

  return {
    deleteConfirmTask,
    setDeleteConfirmTask,
    bulkDeleteConfirm,
    setBulkDeleteConfirm,
    deleteMutation,
    bulkDeleteMutation,
    handleTaskUpdated,
  }
}
