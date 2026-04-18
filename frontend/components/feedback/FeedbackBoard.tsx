'use client'

import { useEffect, useState } from 'react'
import type { FeedbackFilters, FeedbackItem } from '@/lib/api/feedback'
import { FeedbackFilterBar } from './FeedbackFilterBar'
import { FeedbackList } from './FeedbackList'

// ============================================================================
// Types
// ============================================================================

interface FeedbackBoardProps {
  items: FeedbackItem[]
  total: number
  isLoading: boolean
  filters: FeedbackFilters
  onFiltersChange: (filters: Partial<FeedbackFilters>) => void
  onItemClick: (id: string | null) => void
  selectedId: string | null
}

// ============================================================================
// Component
// ============================================================================

export function FeedbackBoard({
  items,
  total,
  isLoading,
  filters,
  onFiltersChange,
  onItemClick,
  selectedId,
}: FeedbackBoardProps) {
  const [searchInput, setSearchInput] = useState(filters.query || '')

  useEffect(() => {
    setSearchInput(filters.query || '')
  }, [filters.query])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    onFiltersChange({ query: searchInput || undefined })
  }

  return (
    <div className="space-y-4">
      <FeedbackFilterBar
        filters={filters}
        onFiltersChange={onFiltersChange}
        total={total}
        searchInput={searchInput}
        onSearchInputChange={setSearchInput}
        onSearchSubmit={handleSearch}
      />
      <FeedbackList
        items={items}
        isLoading={isLoading}
        filters={filters}
        onItemClick={onItemClick}
        selectedId={selectedId}
      />
    </div>
  )
}
