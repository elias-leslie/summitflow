'use client'

import { useQuery } from '@tanstack/react-query'
import { clsx } from 'clsx'
import { MessageSquareWarning } from 'lucide-react'
import { useState } from 'react'
import { ComponentSummary } from '@/components/feedback/ComponentSummary'
import { FeedbackBoard } from '@/components/feedback/FeedbackBoard'
import { FeedbackDetail } from '@/components/feedback/FeedbackDetail'
import { FeedbackStats } from '@/components/feedback/FeedbackStats'
import {
  type FeedbackFilters,
  type FeedbackStatusFilter,
  fetchFeedbackItems,
  fetchFeedbackSummary,
} from '@/lib/api/feedback'

export function FeedbackClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedbackFilters>({
    status: 'active',
    sort: 'votes',
    limit: 50,
  })

  // Fetch summary
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['feedback-summary'],
    queryFn: () => fetchFeedbackSummary(),
    staleTime: 30000,
  })

  // Fetch items with filters
  const { data: itemsData, isLoading: itemsLoading } = useQuery({
    queryKey: ['feedback-items', filters],
    queryFn: () => fetchFeedbackItems(filters),
    staleTime: 15000,
  })

  const handleFiltersChange = (partial: Partial<FeedbackFilters>) => {
    setFilters((prev) => ({ ...prev, ...partial }))
  }

  const handleTypeClick = (type: string | undefined) => {
    handleFiltersChange({ feedback_type: type })
  }

  const handleStatusClick = (status: FeedbackStatusFilter | undefined) => {
    handleFiltersChange({ status })
  }

  const handleComponentClick = (componentId: string | undefined) => {
    handleFiltersChange({ component_id: componentId })
  }

  return (
    <div className="flex h-full">
      {/* Main content */}
      <div
        className={clsx(
          'flex-1 overflow-y-auto p-6 space-y-6 transition-all duration-200',
          selectedId ? 'pr-0' : '',
        )}
      >
        {/* Header */}
        <header>
          <h1 className="display text-xl font-semibold text-slate-100 flex items-center gap-3">
            <MessageSquareWarning className="w-5 h-5 text-outrun-400" />
            Agent Feedback
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            Friction reports, ideas, and praise from AI agents
          </p>
        </header>

        {/* Stats */}
        <FeedbackStats
          summary={summary}
          isLoading={summaryLoading}
          activeType={filters.feedback_type}
          activeStatus={filters.status}
          onTypeClick={handleTypeClick}
          onStatusClick={handleStatusClick}
        />

        {/* Component summary */}
        <ComponentSummary
          summary={summary}
          isLoading={summaryLoading}
          activeComponent={filters.component_id}
          onComponentClick={handleComponentClick}
        />

        {/* Board */}
        <FeedbackBoard
          items={itemsData?.items ?? []}
          total={itemsData?.total ?? 0}
          isLoading={itemsLoading}
          filters={filters}
          onFiltersChange={handleFiltersChange}
          onItemClick={setSelectedId}
          selectedId={selectedId}
        />
      </div>

      {/* Detail panel */}
      {selectedId && (
        <div className="w-[400px] flex-shrink-0 border-l border-slate-700/50 bg-slate-900/80 overflow-hidden animate-in">
          <FeedbackDetail
            itemId={selectedId}
            onClose={() => setSelectedId(null)}
          />
        </div>
      )}
    </div>
  )
}
