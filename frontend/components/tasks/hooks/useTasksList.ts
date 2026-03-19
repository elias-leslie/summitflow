import { useQuery } from '@tanstack/react-query'
import { useMemo, useCallback } from 'react'
import { fetchTasks, type Task } from '@/lib/api'
import { STALE_GIT } from '@/lib/polling'
import { taskQueryKeys } from '@/lib/task-cache'
import type { TaskFilterValues } from '../TaskFilters'

export function useTasksList(
  projectId: string,
  filters: TaskFilterValues,
  sortFn: (tasks: Task[]) => Task[],
) {
  // Fetch all tasks
  const {
    data: tasksData,
    isLoading: tasksLoading,
    isFetching: tasksFetching,
    refetch: refetchTasks,
  } = useQuery({
    queryKey: taskQueryKeys.all(projectId),
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: STALE_GIT,
  })

  // Unified refetch function
  const refetch = useCallback(() => {
    refetchTasks()
  }, [refetchTasks])

  // Apply client-side filters and sorting
  const filteredTasks = useMemo(() => {
    const tasks = tasksData?.tasks || []

    const filtered = tasks.filter((task) => {
      // Type filter
      if (filters.type !== 'all' && task.task_type !== filters.type) {
        return false
      }

      // Status filter (direct match)
      if (
        filters.status !== 'all' &&
        task.status !== filters.status
      ) {
        return false
      }

      // Priority filter
      if (filters.priority !== 'all' && task.priority !== filters.priority) {
        return false
      }

      return true
    })

    return sortFn(filtered)
  }, [tasksData, filters, sortFn])

  const isLoading = tasksLoading
  const isFetching = tasksFetching

  return {
    filteredTasks,
    isLoading,
    isFetching,
    refetch,
  }
}
