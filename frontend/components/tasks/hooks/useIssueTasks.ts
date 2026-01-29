/**
 * Custom hook for Issue Tasks data fetching and mutations
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchReadyTasks,
  fetchTasks,
  type TaskStatus,
  type TaskType,
  updateTaskStatus,
} from '@/lib/api'

export function useIssueTasks(
  projectId: string,
  statusFilter: 'all' | 'pending' | 'completed',
  typeFilter: TaskType | 'all',
) {
  const queryClient = useQueryClient()

  // Fetch ready tasks
  const readyTasksQuery = useQuery({
    queryKey: ['tasks', projectId, 'ready'],
    queryFn: () => fetchReadyTasks(projectId),
    staleTime: 30000,
  })

  // Fetch filtered tasks
  const tasksQuery = useQuery({
    queryKey: ['tasks', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchTasks(projectId, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        type: typeFilter === 'all' ? undefined : typeFilter,
        limit: 200,
      }),
    staleTime: 30000,
  })

  // Status update mutation
  const statusMutation = useMutation({
    mutationFn: ({ taskId, status }: { taskId: string; status: TaskStatus }) =>
      updateTaskStatus(projectId, taskId, status),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['tasks', projectId] })
    },
  })

  return {
    readyTasks: readyTasksQuery.data?.tasks || [],
    tasks: tasksQuery.data?.tasks || [],
    isLoading: tasksQuery.isLoading,
    refetch: tasksQuery.refetch,
    updateStatus: statusMutation.mutate,
    isUpdating: statusMutation.isPending,
  }
}
