/**
 * Custom hook for managing refactor targets data and state
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  fetchRefactorTargets,
  type RefactorTargetsResponse,
} from '../utils/codeHealthApi'
import {
  filterByPriority,
  type PriorityFilter,
  type SortDir,
  type SortField,
  sortTargets,
} from '../utils/codeHealthUtils'

export function useRefactorTargets(projectId: string) {
  const [priorityFilter, setPriorityFilter] = useState<PriorityFilter>('all')
  const [sortField, setSortField] = useState<SortField>('complexity_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())

  const { data, isLoading, error } = useQuery<RefactorTargetsResponse>({
    queryKey: ['refactor-targets', projectId, true],
    queryFn: () => fetchRefactorTargets(projectId, true),
    staleTime: 60000,
    refetchOnWindowFocus: false,
  })

  // Filter and sort targets
  const filteredTargets = useMemo(() => {
    if (!data?.targets) return []
    let result = filterByPriority(data.targets, priorityFilter)
    result = sortTargets(result, sortField, sortDir)
    return result
  }, [data?.targets, priorityFilter, sortField, sortDir])

  // Toggle sort field/direction
  const toggleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortField(field)
      setSortDir('desc')
    }
  }

  // Toggle row expansion
  const toggleRow = (path: string) => {
    const next = new Set(expandedRows)
    if (next.has(path)) {
      next.delete(path)
    } else {
      next.add(path)
    }
    setExpandedRows(next)
  }

  // Derived metrics
  const highCount = data?.summary.high_priority_count ?? 0
  const mediumCount = data?.summary.medium_priority_count ?? 0
  const totalComplexity = data?.summary.total_complexity ?? 0
  const totalTargets = highCount + mediumCount

  return {
    // Data
    data,
    isLoading,
    error,
    filteredTargets,

    // Metrics
    highCount,
    mediumCount,
    totalComplexity,
    totalTargets,

    // Filter state
    priorityFilter,
    setPriorityFilter,

    // Sort state
    sortField,
    sortDir,
    toggleSort,

    // Row expansion state
    expandedRows,
    toggleRow,
  }
}
