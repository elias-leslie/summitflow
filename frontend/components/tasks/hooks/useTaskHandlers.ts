import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { deleteTask, deleteTasks } from '@/lib/api/tasks'
import type { Task } from '@/lib/api'

export function useTaskHandlers(projectId: string) {
  const queryClient = useQueryClient()
  const [deleteConfirmTask, setDeleteConfirmTask] = useState<Task | null>(null)
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)

  // Delete mutations
  const deleteMutation = useMutation({
    mutationFn: (taskId: string) => deleteTask(projectId, taskId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      setDeleteConfirmTask(null)
    },
  })

  const bulkDeleteMutation = useMutation({
    mutationFn: (taskIds: string[]) => deleteTasks(projectId, taskIds),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
      setBulkDeleteConfirm(false)
    },
  })

  // Task update handler
  const handleTaskUpdated = useCallback(
    (updatedTask: Task) => {
      queryClient.setQueryData(
        ['tasks', projectId, 'all'],
        (old: { tasks: Task[] } | undefined) => {
          if (!old) return old
          return {
            ...old,
            tasks: old.tasks.map((t) =>
              t.id === updatedTask.id ? updatedTask : t,
            ),
          }
        },
      )
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
