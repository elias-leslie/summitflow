import { useQuery } from '@tanstack/react-query'
import { useMemo, useCallback } from 'react'
import { fetchBlockedTasks, fetchTasks, type Task } from '@/lib/api'
import { taskQueryKeys } from '@/lib/task-cache'
import type { TaskFilterValues } from '../TaskFilters'

function mergeBlockedTasks(tasks: Task[], dependencyBlockedTasks: Task[]): Task[] {
  const merged = new Map<string, Task>()

  for (const task of tasks) {
    if (task.status === 'blocked' || task.status === 'conflicted') {
      merged.set(task.id, task)
    }
  }

  for (const task of dependencyBlockedTasks) {
    merged.set(task.id, task)
  }

  return Array.from(merged.values())
}

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
    staleTime: 30000,
  })

  // Fetch blocked tasks (separate query since it's a different endpoint)
  const {
    data: blockedTasksData,
    isLoading: blockedLoading,
    isFetching: blockedFetching,
    refetch: refetchBlocked,
  } = useQuery({
    queryKey: taskQueryKeys.blocked(projectId),
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
        ? mergeBlockedTasks(tasksData?.tasks || [], blockedTasksData?.tasks || [])
        : tasksData?.tasks || []

    const filtered = tasks.filter((task) => {
      // Type filter
      if (filters.type !== 'all' && task.task_type !== filters.type) {
        return false
      }

      // Status filter (direct match)
      if (
        filters.status !== 'all' &&
        filters.status !== 'blocked' &&
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
