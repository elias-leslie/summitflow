import { useQuery } from '@tanstack/react-query'
import { useMemo, useCallback } from 'react'
import { fetchBlockedTasks, fetchTasks, type Task } from '@/lib/api'
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
    queryKey: ['tasks', projectId, 'all'],
    queryFn: () => fetchTasks(projectId, { limit: 500 }),
    staleTime: 30000,
  })

  // Fetch blocked tasks (separate query since it's a different endpoint)
  const {
    data: blockedTasksData,
    isLoading: blockedLoading,
    isFetching: blockedFetching,
    refetch: refetchBlocked,
  } = useQuery({
    queryKey: ['tasks', projectId, 'blocked'],
    queryFn: () => fetchBlockedTasks(projectId, 500),
    staleTime: 30000,
    enabled: filters.status === 'blocked', // Only fetch when filter is blocked
  })

  // Unified refetch function
  const refetch = useCallback(() => {
    refetchTasks()
    if (filters.status === 'blocked') {
      refetchBlocked()
    }
  }, [refetchTasks, refetchBlocked, filters.status])

  // Apply client-side filters and sorting
  const filteredTasks = useMemo(() => {
    // For "blocked" status, use the blocked tasks endpoint data
    const tasks =
      filters.status === 'blocked'
        ? blockedTasksData?.tasks || []
        : tasksData?.tasks || []

    const isCrowdsourced = (t: Task) =>
      t.labels?.some((l) => l.toLowerCase() === 'crowdsourced')

    const filtered = tasks.filter((task) => {
      // Type filter
      if (filters.type !== 'all' && task.task_type !== filters.type) {
        return false
      }

      // Phase filter (maps pipeline phases to underlying statuses)
      if (filters.status !== 'all' && filters.status !== 'blocked') {
        switch (filters.status) {
          case 'active':
            if (
              task.status === 'completed' ||
              task.status === 'failed' ||
              task.status === 'cancelled'
            )
              return false
            break
          case 'ideation':
            if (task.status !== 'pending' || !isCrowdsourced(task))
              return false
            break
          case 'planning':
            if (task.status !== 'pending' || isCrowdsourced(task))
              return false
            break
          case 'queue':
            if (task.status !== 'queue') return false
            break
          case 'executing':
            if (task.status !== 'running' && task.status !== 'paused')
              return false
            break
          case 'reviewing':
            if (task.status !== 'ai_reviewing') return false
            break
          case 'integrating':
            if (task.status !== 'pr_created') return false
            break
          case 'completed':
            if (task.status !== 'completed') return false
            break
          case 'failed':
            if (task.status !== 'failed') return false
            break
        }
      }

      // Priority filter
      if (filters.priority !== 'all' && task.priority !== filters.priority) {
        return false
      }

      return true
    })

    return sortFn(filtered)
  }, [tasksData, blockedTasksData, filters, sortFn])

  const isLoading = filters.status === 'blocked' ? blockedLoading : tasksLoading
  const isFetching =
    filters.status === 'blocked' ? blockedFetching : tasksFetching

  return {
    filteredTasks,
    isLoading,
    isFetching,
    refetch,
  }
}
