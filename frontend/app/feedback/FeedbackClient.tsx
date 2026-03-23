'use client'

import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { ComponentSummary } from '@/components/feedback/ComponentSummary'
import { FeedbackBoard } from '@/components/feedback/FeedbackBoard'
import { FeedbackStats } from '@/components/feedback/FeedbackStats'
import {
  type FeedbackFilters,
  type FeedbackStatusFilter,
  fetchFeedbackItems,
  fetchFeedbackSummary,
} from '@/lib/api/feedback'
import { STALE_GIT, STALE_STANDARD } from '@/lib/polling'

export function FeedbackClient() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [filters, setFilters] = useState<FeedbackFilters>({
    status: 'active',
    sort: 'votes',
    limit: 50,
  })

  // Fetch summary
  const { data: summary, isLoading: summaryLoading, error: summaryError } = useQuery({
    queryKey: ['feedback-summary'],
    queryFn: () => fetchFeedbackSummary(),
    staleTime: STALE_GIT,
  })

  // Fetch items with filters
  const { data: itemsData, isLoading: itemsLoading, error: itemsError } = useQuery({
    queryKey: ['feedback-items', filters],
    queryFn: () => fetchFeedbackItems(filters),
    staleTime: STALE_STANDARD,
  })

  const error = summaryError || itemsError

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
    <div className="overflow-y-auto h-full">
      <div className="p-6 space-y-5 max-w-7xl mx-auto">
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-slate-100 display tracking-tight">
              Agent Feedback
            </h1>
            <p className="text-sm text-slate-400 mt-0.5">
              Friction reports, ideas, and praise from AI agents
            </p>
          </div>
          {summary && (
            <div className="hidden sm:flex items-center gap-3 text-sm">
              <span className="text-slate-500">
                {summary.total} signals
              </span>
            </div>
          )}
        </div>

        {/* Error state */}
        {error && (
          <div className="rounded-lg border border-rose-500/20 bg-rose-500/10 p-4 text-sm text-rose-300">
            Failed to load feedback data. Verify the backend is running.
          </div>
        )}

        {/* Health bar + stat pills */}
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
        <section className="space-y-3">
          <div>
            <h2 className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-300">
              Feedback
            </h2>
            <p className="mt-0.5 text-xs text-slate-500">
              All agent reports and signals
            </p>
          </div>
          <FeedbackBoard
            items={itemsData?.items ?? []}
            total={itemsData?.total ?? 0}
            isLoading={itemsLoading}
            filters={filters}
            onFiltersChange={handleFiltersChange}
            onItemClick={setSelectedId}
            selectedId={selectedId}
          />
        </section>
      </div>
    </div>
  )
}
