'use client'

import { useCallback, useState } from 'react'
import {
  DEFAULT_EXPANDED_ROWS,
  ROWS,
  type TaskKanbanColumn,
} from '../columnConfig'

const STORAGE_KEY_PREFIX = 'kanban-collapsed-rows'

function getStorageKey(projectId: string): string {
  return `${STORAGE_KEY_PREFIX}:${projectId}`
}

function loadCollapsed(projectId: string): Set<TaskKanbanColumn> {
  if (typeof window === 'undefined') {
    return getDefaultCollapsed()
  }
  try {
    const stored = localStorage.getItem(getStorageKey(projectId))
    if (stored) {
      return new Set(JSON.parse(stored) as TaskKanbanColumn[])
    }
  } catch {
    // Corrupted localStorage — fall through to defaults
  }
  return getDefaultCollapsed()
}

function getDefaultCollapsed(): Set<TaskKanbanColumn> {
  const expandedSet = new Set<TaskKanbanColumn>(DEFAULT_EXPANDED_ROWS)
  return new Set(ROWS.map((r) => r.id).filter((id) => !expandedSet.has(id)))
}

export function useRowCollapse(projectId: string) {
  const [collapsed, setCollapsed] = useState<Set<TaskKanbanColumn>>(() =>
    loadCollapsed(projectId),
  )

  const isCollapsed = useCallback(
    (rowId: TaskKanbanColumn): boolean => collapsed.has(rowId),
    [collapsed],
  )

  const toggleRow = useCallback(
    (rowId: TaskKanbanColumn) => {
      setCollapsed((prev) => {
        const next = new Set(prev)
        if (next.has(rowId)) {
          next.delete(rowId)
        } else {
          next.add(rowId)
        }
        try {
          localStorage.setItem(
            getStorageKey(projectId),
            JSON.stringify([...next]),
          )
        } catch {
          // localStorage full or unavailable — state still works in memory
        }
        return next
      })
    },
    [projectId],
  )

  return { isCollapsed, toggleRow }
}
