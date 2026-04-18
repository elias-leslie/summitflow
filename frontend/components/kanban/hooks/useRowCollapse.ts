'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import { ALWAYS_COLLAPSED, ROWS, type TaskKanbanColumn } from '../columnConfig'

const STORAGE_KEY_PREFIX = 'kanban-collapsed-rows'

function getStorageKey(projectId: string): string {
  return `${STORAGE_KEY_PREFIX}:${projectId}`
}

// Returns null when no stored state exists (first visit)
function loadStoredCollapsed(projectId: string): Set<TaskKanbanColumn> | null {
  if (typeof window === 'undefined') return null
  try {
    const stored = localStorage.getItem(getStorageKey(projectId))
    if (stored) {
      return new Set(JSON.parse(stored) as TaskKanbanColumn[])
    }
  } catch {
    // Corrupted localStorage — fall through
  }
  return null
}

// Persist collapsed state, excluding always-collapsed rows
function saveCollapsed(projectId: string, collapsed: Set<TaskKanbanColumn>) {
  const toStore = [...collapsed].filter(
    (id) => !(ALWAYS_COLLAPSED as readonly string[]).includes(id),
  )
  try {
    localStorage.setItem(getStorageKey(projectId), JSON.stringify(toStore))
  } catch {
    // localStorage full or unavailable — state still works in memory
  }
}

// Smart defaults: expand rows with tasks, collapse empty + always-collapsed
function computeDefaultCollapsed(
  taskCounts: Record<TaskKanbanColumn, number>,
): Set<TaskKanbanColumn> {
  return new Set(
    ROWS.map((r) => r.id).filter(
      (id) =>
        (ALWAYS_COLLAPSED as readonly string[]).includes(id) ||
        taskCounts[id] === 0,
    ),
  )
}

export function useRowCollapse(
  projectId: string,
  taskCounts: Record<TaskKanbanColumn, number>,
) {
  const prevCountsRef = useRef(taskCounts)

  const [collapsed, setCollapsed] = useState<Set<TaskKanbanColumn>>(() => {
    const stored = loadStoredCollapsed(projectId)
    if (stored) {
      // Enforce always-collapsed rows regardless of stored state
      for (const id of ALWAYS_COLLAPSED) {
        stored.add(id)
      }
      return stored
    }
    // No stored state — use smart defaults
    return computeDefaultCollapsed(taskCounts)
  })

  // Detect 0→N transitions and auto-expand (except always-collapsed rows)
  useEffect(() => {
    const prev = prevCountsRef.current
    const rowsToExpand: TaskKanbanColumn[] = []

    for (const row of ROWS) {
      if ((ALWAYS_COLLAPSED as readonly string[]).includes(row.id)) continue
      if (prev[row.id] === 0 && taskCounts[row.id] > 0) {
        rowsToExpand.push(row.id)
      }
    }

    if (rowsToExpand.length > 0) {
      setCollapsed((current) => {
        const next = new Set(current)
        for (const id of rowsToExpand) {
          next.delete(id)
        }
        saveCollapsed(projectId, next)
        return next
      })
    }

    prevCountsRef.current = taskCounts
  }, [taskCounts, projectId])

  const isCollapsed = useCallback(
    (rowId: TaskKanbanColumn): boolean => collapsed.has(rowId),
    [collapsed],
  )

  const toggleRow = useCallback(
    (rowId: TaskKanbanColumn) => {
      setCollapsed((current) => {
        const next = new Set(current)
        if (next.has(rowId)) {
          next.delete(rowId)
        } else {
          next.add(rowId)
        }
        saveCollapsed(projectId, next)
        return next
      })
    },
    [projectId],
  )

  return { isCollapsed, toggleRow }
}
