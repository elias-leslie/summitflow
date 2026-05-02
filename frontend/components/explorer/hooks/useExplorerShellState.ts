/**
 * useExplorerShellState - Hook for managing top-level explorer shell UI state
 */

import { useCallback, useState } from 'react'
import type { ExplorerType, HealthStatus } from '../types'
import { nextSortState, toggleSetValue } from './stateUtils'

export interface ExplorerShellState {
  activeType: ExplorerType
  activeFilter: HealthStatus | 'all'
  sortField: string
  sortDir: 'asc' | 'desc'
  expandedIds: Set<string>
}

export interface ExplorerShellStateHandlers {
  handleTypeChange: (type: ExplorerType) => void
  handleFilterChange: (filter: HealthStatus | 'all') => void
  handleSort: (field: string) => void
  handleToggleExpand: (id: string) => void
  handleCollapseAll: () => void
}

export interface UseExplorerShellStateReturn
  extends ExplorerShellState,
    ExplorerShellStateHandlers {}

export function useExplorerShellState(
  initialType: ExplorerType = 'files',
  onTypeChange?: (type: ExplorerType) => void,
): UseExplorerShellStateReturn {
  const [activeType, setActiveType] = useState<ExplorerType>(initialType)
  const [activeFilter, setActiveFilter] = useState<HealthStatus | 'all'>('all')
  const [sortField, setSortField] = useState('name')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('asc')
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set())

  const handleTypeChange = useCallback(
    (type: ExplorerType) => {
      setActiveType(type)
      setActiveFilter('all')
      setExpandedIds(new Set())
      setSortField('name')
      setSortDir('asc')
      onTypeChange?.(type)
    },
    [onTypeChange],
  )

  const handleFilterChange = useCallback((filter: HealthStatus | 'all') => {
    setActiveFilter(filter)
  }, [])

  const handleSort = useCallback(
    (field: string) => {
      const next = nextSortState(sortField, sortDir, field)
      setSortField(next.field)
      setSortDir(next.dir)
    },
    [sortField, sortDir],
  )

  const handleToggleExpand = useCallback((id: string) => {
    setExpandedIds((prev) => toggleSetValue(prev, id))
  }, [])

  const handleCollapseAll = useCallback(() => {
    setExpandedIds(new Set())
  }, [])

  return {
    activeType,
    activeFilter,
    sortField,
    sortDir,
    expandedIds,
    handleTypeChange,
    handleFilterChange,
    handleSort,
    handleToggleExpand,
    handleCollapseAll,
  }
}
