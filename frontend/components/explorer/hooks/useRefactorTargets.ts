/**
 * Custom hook for managing refactor targets data and state
 */

import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { POLL_SLOW } from '@/lib/polling'
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
  const [sortField, setSortField] = useState<SortField>('hotspot_score')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set())

  const { data, isLoading, error } = useQuery<RefactorTargetsResponse>({
    queryKey: ['refactor-targets', projectId, true],
    queryFn: () => fetchRefactorTargets(projectId, { codeOnly: true }),
    staleTime: POLL_SLOW,
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
  const actionableCount =
    data?.targets.filter((target) => target.should_create_task).length ?? 0
  const observeOnlyCount =
    data?.targets.filter(
      (target) =>
        !target.should_create_task &&
        target.recommended_action === 'keep_in_explorer',
    ).length ?? 0

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
    actionableCount,
    observeOnlyCount,

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
