import { useCallback, useState } from 'react'
import type { Task } from '@/lib/api'

export function useTaskSelection() {
  const [selectedTaskIds, setSelectedTaskIds] = useState<Set<string>>(new Set())

  const handleToggleSelect = useCallback((taskId: string) => {
    setSelectedTaskIds((prev) => {
      const next = new Set(prev)
      if (next.has(taskId)) {
        next.delete(taskId)
      } else {
        next.add(taskId)
      }
      return next
    })
  }, [])

  const handleToggleSelectAll = useCallback((tasks: Task[]) => {
    setSelectedTaskIds((prev) => {
      if (prev.size === tasks.length) {
        return new Set()
      } else {
        return new Set(tasks.map((t) => t.id))
      }
    })
  }, [])

  const clearSelection = useCallback(() => {
    setSelectedTaskIds(new Set())
  }, [])

  return {
    selectedTaskIds,
    handleToggleSelect,
    handleToggleSelectAll,
    clearSelection,
  }
}
