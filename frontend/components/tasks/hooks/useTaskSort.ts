import { useState } from 'react'
import type { Task } from '@/lib/api'

export type SortField = 'priority' | 'created_at' | 'title' | 'status' | 'type'
export type SortDirection = 'asc' | 'desc'

export function useTaskSort() {
  const [sortField, setSortField] = useState<SortField>('created_at')
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc')

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDirection(field === 'created_at' ? 'desc' : 'asc')
    }
  }

  const sortTasks = (tasks: Task[]): Task[] => {
    return [...tasks].sort((a, b) => {
      let comparison = 0
      switch (sortField) {
        case 'priority':
          comparison = (a.priority ?? 2) - (b.priority ?? 2)
          break
        case 'created_at':
          comparison =
            new Date(a.created_at || 0).getTime() -
            new Date(b.created_at || 0).getTime()
          break
        case 'title':
          comparison = a.title.localeCompare(b.title)
          break
        case 'status':
          comparison = a.status.localeCompare(b.status)
          break
        case 'type':
          comparison = (a.task_type || 'task').localeCompare(
            b.task_type || 'task',
          )
          break
      }
      return sortDirection === 'asc' ? comparison : -comparison
    })
  }

  return {
    sortField,
    sortDirection,
    handleSort,
    sortTasks,
  }
}
