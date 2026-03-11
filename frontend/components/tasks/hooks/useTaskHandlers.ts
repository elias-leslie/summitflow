import { useMutation } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'
import { deleteTask, deleteTasks } from '@/lib/api/tasks'
import type { Task } from '@/lib/api'
import { useTaskMutationSync } from '@/lib/task-mutation-sync'

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
      console.error('Failed to delete task:', error)
      toast.error('Failed to delete task')
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
    handleTaskUpdated,
  }
}
