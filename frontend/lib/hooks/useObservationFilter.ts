'use client'

import { useCallback, useMemo, useState } from 'react'
import type {
  ConceptType,
  ObservationType,
} from '@/lib/formatters/observation-colors'

export interface UseObservationFilterReturn {
  typeFilter: ObservationType | 'all'
  setTypeFilter: (filter: ObservationType | 'all') => void
  conceptFilters: Set<ConceptType>
  showFilters: boolean
  setShowFilters: (show: boolean) => void
  toggleConceptFilter: (concept: ConceptType) => void
  clearFilters: () => void
  hasActiveFilters: boolean
}

export function useObservationFilter(): UseObservationFilterReturn {
  const [typeFilter, setTypeFilter] = useState<ObservationType | 'all'>('all')
  const [conceptFilters, setConceptFilters] = useState<Set<ConceptType>>(
    new Set(),
  )
  const [showFilters, setShowFilters] = useState(false)

  const toggleConceptFilter = useCallback((concept: ConceptType) => {
    setConceptFilters((prev) => {
      const next = new Set(prev)
      if (next.has(concept)) {
        next.delete(concept)
      } else {
        next.add(concept)
      }
      return next
    })
  }, [])

  const clearFilters = useCallback(() => {
    setTypeFilter('all')
    setConceptFilters(new Set())
  }, [])

  const hasActiveFilters = useMemo(
    () => typeFilter !== 'all' || conceptFilters.size > 0,
    [typeFilter, conceptFilters],
  )

  return {
    typeFilter,
    setTypeFilter,
    conceptFilters,
    showFilters,
    setShowFilters,
    toggleConceptFilter,
    clearFilters,
    hasActiveFilters,
  }
}
